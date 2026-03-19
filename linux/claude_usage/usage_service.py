"""OAuth usage service — ported from UsageService.swift.

All HTTP is done via ``urllib.request`` (stdlib only).  The caller is
expected to invoke ``fetch_usage()`` / ``fetch_profile()`` from a background
thread; the ``on_state_changed`` callback (if set) will be called from that
same thread — the GUI layer should marshal to the main thread.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Any

from .credentials import CredentialsStore, StoredCredentials
from .history_service import UsageHistoryService
from .models import UsageResponse
from .notification_service import NotificationService


# ---------------------------------------------------------------------------
# OAuth constants
# ---------------------------------------------------------------------------

_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_AUTHORIZE_ENDPOINT = "https://claude.ai/oauth/authorize"
_TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
_USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
_USERINFO_ENDPOINT = "https://api.anthropic.com/api/oauth/userinfo"
_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
_DEFAULT_SCOPES = ["user:profile", "user:inference"]
_BETA_HEADER = "oauth-2025-04-20"
_MAX_BACKOFF_INTERVAL = 3600.0  # 1 hour
_USER_AGENT = "ClaudeUsage/1.1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_code_verifier() -> str:
    return _base64url(secrets.token_bytes(32))


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _base64url(digest)


# ---------------------------------------------------------------------------
# UsageService
# ---------------------------------------------------------------------------

class UsageService:
    """Manages OAuth authentication and usage polling."""

    default_polling_minutes: int = 30
    polling_options = [5, 15, 30, 60]

    def __init__(
        self,
        credentials_store: Optional[CredentialsStore] = None,
        usage_endpoint: str = _USAGE_ENDPOINT,
        userinfo_endpoint: str = _USERINFO_ENDPOINT,
        token_endpoint: str = _TOKEN_ENDPOINT,
        redirect_uri: str = _REDIRECT_URI,
    ) -> None:
        self.credentials_store = credentials_store or CredentialsStore()
        self._usage_endpoint = usage_endpoint
        self._userinfo_endpoint = userinfo_endpoint
        self._token_endpoint = token_endpoint
        self._redirect_uri = redirect_uri

        # Public observable state
        self.is_authenticated: bool = False
        self.is_awaiting_code: bool = False
        self.usage: Optional[UsageResponse] = None
        self.account_email: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_updated: Optional[datetime] = None
        self.polling_minutes: int = self.default_polling_minutes

        # Interval tracking
        self._current_interval: float = float(self.polling_minutes * 60)

        # PKCE state
        self._code_verifier: Optional[str] = None
        self._oauth_state: Optional[str] = None

        # Refresh lock — prevents concurrent refresh attempts
        self._refresh_lock = threading.Lock()

        # External hooks
        self.history_service: Optional[UsageHistoryService] = None
        self.notification_service: Optional[NotificationService] = None
        self.on_state_changed: Optional[Callable[[], None]] = None

        # Attempt to load existing credentials
        self.is_authenticated = self.credentials_store.load(
            default_scopes=_DEFAULT_SCOPES
        ) is not None

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def pct_5h(self) -> float:
        return (self.usage.five_hour.utilization or 0) / 100.0 if self.usage and self.usage.five_hour else 0.0

    @property
    def pct_7d(self) -> float:
        return (self.usage.seven_day.utilization or 0) / 100.0 if self.usage and self.usage.seven_day else 0.0

    @property
    def pct_extra(self) -> float:
        return (self.usage.extra_usage.utilization or 0) / 100.0 if self.usage and self.usage.extra_usage else 0.0

    @property
    def _base_interval(self) -> float:
        return float(self.polling_minutes * 60)

    # ------------------------------------------------------------------
    # Backoff
    # ------------------------------------------------------------------

    @staticmethod
    def backoff_interval(
        retry_after: Optional[float],
        current_interval: float,
    ) -> float:
        doubled = current_interval * 2
        candidate = max(retry_after or doubled, doubled)
        return min(candidate, _MAX_BACKOFF_INTERVAL)

    # ------------------------------------------------------------------
    # OAuth PKCE flow
    # ------------------------------------------------------------------

    def start_oauth_flow(self) -> str:
        """Initiate PKCE flow: open browser and return the authorize URL."""
        verifier = _generate_code_verifier()
        challenge = _generate_code_challenge(verifier)
        state = _generate_code_verifier()  # random state

        self._code_verifier = verifier
        self._oauth_state = state

        params = {
            "code": "true",
            "client_id": _CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": " ".join(_DEFAULT_SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }

        query = "&".join(
            f"{k}={urllib.request.quote(v, safe='')}" for k, v in params.items()
        )
        url = f"{_AUTHORIZE_ENDPOINT}?{query}"

        webbrowser.open(url)
        self.is_awaiting_code = True
        self._notify()
        return url

    def submit_oauth_code(self, raw_code: str) -> None:
        """Exchange an authorization code (possibly ``code#state``) for tokens.

        This method performs network I/O and should be called from a worker thread.
        """
        raw_code = raw_code.strip()
        parts = raw_code.split("#", 1)
        code = parts[0]

        if len(parts) > 1:
            returned_state = parts[1]
            if returned_state != self._oauth_state:
                self.last_error = "OAuth state mismatch -- try again"
                self.is_awaiting_code = False
                self._code_verifier = None
                self._oauth_state = None
                self._notify()
                return

        verifier = self._code_verifier
        if not verifier:
            self.last_error = "No pending OAuth flow"
            self.is_awaiting_code = False
            self._notify()
            return

        body = json.dumps({
            "grant_type": "authorization_code",
            "code": code,
            "state": self._oauth_state or "",
            "client_id": _CLIENT_ID,
            "redirect_uri": self._redirect_uri,
            "code_verifier": verifier,
        }).encode()

        req = urllib.request.Request(
            self._token_endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            resp_json = json.loads(data)
        except urllib.error.HTTPError as e:
            body_str = ""
            try:
                body_str = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            self.last_error = f"Token exchange failed: HTTP {e.code} {body_str}"
            self._notify()
            return
        except Exception as e:
            self.last_error = f"Token exchange error: {e}"
            self._notify()
            return

        credentials = self._credentials_from_json(resp_json)
        if credentials is None:
            self.last_error = "Could not parse token response"
            self._notify()
            return

        try:
            self.credentials_store.save(credentials)
        except Exception as e:
            self.last_error = f"Failed to save credentials: {e}"
            self._notify()
            return

        self.is_authenticated = True
        self.is_awaiting_code = False
        self.last_error = None
        self._code_verifier = None
        self._oauth_state = None
        self._notify()

        self.fetch_profile()
        self.fetch_usage()

    # ------------------------------------------------------------------
    # Sign out
    # ------------------------------------------------------------------

    def sign_out(self) -> None:
        self.credentials_store.delete()
        self.is_authenticated = False
        self.usage = None
        self.last_updated = None
        self.account_email = None
        self.last_error = None
        self._code_verifier = None
        self._oauth_state = None
        self._notify()

    # ------------------------------------------------------------------
    # Fetch usage
    # ------------------------------------------------------------------

    def fetch_usage(self) -> None:
        """GET usage endpoint.  Handles 401 (refresh+retry) and 429 (backoff).

        This performs network I/O — call from a worker thread.
        """
        result = self._send_authorized_request(self._usage_endpoint)
        if result is None:
            return

        status, data, headers = result

        if status == 429:
            retry_after_str = headers.get("Retry-After")
            retry_after: Optional[float] = None
            if retry_after_str:
                try:
                    retry_after = float(retry_after_str)
                except ValueError:
                    pass
            self._current_interval = self.backoff_interval(
                retry_after, self._current_interval
            )
            self.last_error = f"Rate limited -- backing off to {int(self._current_interval)}s"
            self._notify()
            return

        if status != 200:
            self.last_error = f"HTTP {status}"
            self._notify()
            return

        try:
            resp_json = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            self.last_error = "Invalid JSON in usage response"
            self._notify()
            return

        decoded = UsageResponse.from_dict(resp_json)
        reconciled = decoded.reconciled(previous=self.usage)
        self.usage = reconciled
        self.last_error = None
        self.last_updated = datetime.now(timezone.utc)

        # Record history
        if self.history_service is not None:
            pct_sonnet_7d: Optional[float] = None
            if reconciled.seven_day_sonnet and reconciled.seven_day_sonnet.utilization is not None:
                pct_sonnet_7d = reconciled.seven_day_sonnet.utilization / 100.0
            self.history_service.record_data_point(
                pct_5h=self.pct_5h,
                pct_7d=self.pct_7d,
                pct_sonnet_7d=pct_sonnet_7d,
            )

        # Check notification thresholds
        if self.notification_service is not None:
            self.notification_service.check_and_notify(
                pct_5h=self.pct_5h,
                pct_7d=self.pct_7d,
                pct_extra=self.pct_extra,
            )

        # Reset backoff if we had a successful request
        if self._current_interval != self._base_interval:
            self._current_interval = self._base_interval

        self._notify()

    # ------------------------------------------------------------------
    # Fetch profile
    # ------------------------------------------------------------------

    def fetch_profile(self) -> None:
        """Attempt to read the account email.  Tries local config first."""
        local = self._load_local_profile()
        if local:
            self.account_email = local
            self._notify()
            return

        result = self._send_authorized_request(
            self._userinfo_endpoint,
            expire_session_on_auth_failure=False,
        )
        if result is None:
            return

        status, data, _ = result
        if status != 200:
            return

        try:
            info = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return

        email = info.get("email", "")
        if email:
            self.account_email = email
        else:
            name = info.get("name", "")
            if name:
                self.account_email = name
        self._notify()

    # ------------------------------------------------------------------
    # Polling interval
    # ------------------------------------------------------------------

    def update_polling_interval(self, minutes: int) -> None:
        self.polling_minutes = minutes
        self._current_interval = float(minutes * 60)

    # ------------------------------------------------------------------
    # Internal: authorized request with refresh/retry logic
    # ------------------------------------------------------------------

    def _send_authorized_request(
        self,
        url: str,
        expire_session_on_auth_failure: bool = True,
    ) -> Optional[tuple]:
        """Returns ``(status, body_bytes, headers_dict)`` or ``None``."""
        initial = self.credentials_store.load(default_scopes=_DEFAULT_SCOPES)
        if initial is None:
            self.last_error = "Not signed in"
            self.is_authenticated = False
            self._notify()
            return None

        # Proactive refresh if near expiry
        if initial.needs_refresh():
            refresh_ok = self._perform_refresh()
            if not refresh_ok and initial.is_expired():
                if expire_session_on_auth_failure:
                    self._expire_session()
                else:
                    self.last_error = "Token refresh failed -- will retry"
                    self._notify()
                return None

        active = self.credentials_store.load(default_scopes=_DEFAULT_SCOPES) or initial
        status, data, headers = self._do_authorized_get(active.access_token, url)

        if status != 401:
            return (status, data, headers)

        # 401 — try refreshing and retrying once
        refresh_ok = self._perform_refresh()
        if not refresh_ok:
            if expire_session_on_auth_failure:
                self._expire_session()
            else:
                self.last_error = "Token refresh failed -- will retry"
                self._notify()
            return None

        refreshed = self.credentials_store.load(default_scopes=_DEFAULT_SCOPES)
        if refreshed is None:
            if expire_session_on_auth_failure:
                self._expire_session()
            return None

        status, data, headers = self._do_authorized_get(refreshed.access_token, url)
        if status == 401:
            if expire_session_on_auth_failure:
                self._expire_session()
            return None

        return (status, data, headers)

    def _do_authorized_get(
        self, token: str, url: str
    ) -> tuple:
        """Perform a GET with Bearer auth.  Returns ``(status, body, headers)``."""
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("anthropic-beta", _BETA_HEADER)
        req.add_header("User-Agent", _USER_AGENT)

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            return (resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            return (e.code, body, dict(e.headers) if e.headers else {})
        except Exception as e:
            self.last_error = str(e)
            self._notify()
            return (0, b"", {})

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    def _perform_refresh(self) -> bool:
        """Attempt to refresh the access token.  Returns True on success."""
        with self._refresh_lock:
            current = self.credentials_store.load(default_scopes=_DEFAULT_SCOPES)
            if current is None or not current.has_refresh_token:
                return False

            body = {
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
                "client_id": _CLIENT_ID,
            }
            if current.scopes:
                body["scope"] = " ".join(current.scopes)

            req = urllib.request.Request(
                self._token_endpoint,
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                method="POST",
            )

            try:
                resp = urllib.request.urlopen(req, timeout=15)
                resp_data = resp.read()
                status = resp.status
            except urllib.error.HTTPError as e:
                # 4xx = permanent, 5xx = transient
                return False
            except Exception:
                return False

            if status != 200:
                return False

            try:
                resp_json = json.loads(resp_data)
            except (json.JSONDecodeError, ValueError):
                return False

            updated = self._credentials_from_json(resp_json, fallback=current)
            if updated is None:
                return False

            try:
                self.credentials_store.save(updated)
            except Exception:
                return False

            self.is_authenticated = True
            return True

    # ------------------------------------------------------------------
    # Parse token response
    # ------------------------------------------------------------------

    def _credentials_from_json(
        self,
        data: dict,
        fallback: Optional[StoredCredentials] = None,
    ) -> Optional[StoredCredentials]:
        access_token = data.get("access_token", "")
        if not access_token:
            return None

        scope_str = data.get("scope")
        if scope_str:
            scopes = scope_str.split()
        elif fallback and fallback.scopes:
            scopes = list(fallback.scopes)
        else:
            scopes = list(_DEFAULT_SCOPES)

        refresh_token = data.get("refresh_token") or (fallback.refresh_token if fallback else None)
        expires_at = self._expiration_date(data.get("expires_in")) or (fallback.expires_at if fallback else None)

        return StoredCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scopes,
        )

    @staticmethod
    def _expiration_date(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)

    # ------------------------------------------------------------------
    # Local profile fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _load_local_profile() -> Optional[str]:
        path = os.path.join(os.path.expanduser("~"), ".claude.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

        account = data.get("oauthAccount")
        if not isinstance(account, dict):
            return None
        email = account.get("emailAddress", "")
        if email:
            return email
        name = account.get("displayName", "")
        if name:
            return name
        return None

    # ------------------------------------------------------------------
    # Session expiry
    # ------------------------------------------------------------------

    def _expire_session(self) -> None:
        self.credentials_store.delete()
        self.is_authenticated = False
        self.usage = None
        self.last_updated = None
        self.account_email = None
        self.last_error = "Session expired -- please sign in again"
        self._notify()

    # ------------------------------------------------------------------
    # State change notification
    # ------------------------------------------------------------------

    def _notify(self) -> None:
        if self.on_state_changed is not None:
            self.on_state_changed()
