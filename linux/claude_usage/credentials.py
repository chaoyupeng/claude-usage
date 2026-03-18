"""Credential storage — ported from StoredCredentials.swift."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List


# ---------------------------------------------------------------------------
# StoredCredentials
# ---------------------------------------------------------------------------

@dataclass
class StoredCredentials:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)

    @property
    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token)

    def needs_refresh(self, now: Optional[datetime] = None, leeway: float = 300) -> bool:
        """Return True if the token has a refresh token and will expire within *leeway* seconds."""
        if not self.has_refresh_token or self.expires_at is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        return self.expires_at <= now + timedelta(seconds=leeway)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if self.expires_at is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        return self.expires_at <= now

    # -- Serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        d: dict = {
            "accessToken": self.access_token,
            "scopes": self.scopes,
        }
        if self.refresh_token is not None:
            d["refreshToken"] = self.refresh_token
        if self.expires_at is not None:
            d["expiresAt"] = self.expires_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> StoredCredentials:
        expires_at_raw = data.get("expiresAt")
        expires_at: Optional[datetime] = None
        if expires_at_raw:
            normalised = expires_at_raw.replace("Z", "+00:00")
            try:
                expires_at = datetime.fromisoformat(normalised)
            except (ValueError, TypeError):
                pass
        return cls(
            access_token=data.get("accessToken", ""),
            refresh_token=data.get("refreshToken"),
            expires_at=expires_at,
            scopes=data.get("scopes", []),
        )


# ---------------------------------------------------------------------------
# CredentialsStore
# ---------------------------------------------------------------------------

class CredentialsStore:
    """Persists credentials as JSON in a config directory."""

    def __init__(self, directory: Optional[str] = None):
        if directory is None:
            directory = os.path.join(
                os.path.expanduser("~"), ".config", "claude-usage-bar"
            )
        self.directory = directory
        self._credentials_path = os.path.join(directory, "credentials.json")
        self._legacy_token_path = os.path.join(directory, "token")

    def _ensure_directory(self) -> None:
        os.makedirs(self.directory, mode=0o700, exist_ok=True)

    def save(self, credentials: StoredCredentials) -> None:
        """Write credentials to disk with 0600 permissions and remove any legacy token file."""
        self._ensure_directory()
        data = json.dumps(credentials.to_dict(), indent=2)
        # Write atomically: write to tmp then rename
        tmp_path = self._credentials_path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(data)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self._credentials_path)
        # Remove legacy token file if present
        try:
            os.remove(self._legacy_token_path)
        except FileNotFoundError:
            pass

    def load(self, default_scopes: Optional[List[str]] = None) -> Optional[StoredCredentials]:
        """Load credentials from the JSON file, falling back to a legacy plain-text token."""
        if default_scopes is None:
            default_scopes = []

        # Try the modern credentials file first
        try:
            with open(self._credentials_path, "r") as f:
                data = json.load(f)
            return StoredCredentials.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        # Fallback: legacy plain-text token file
        try:
            with open(self._legacy_token_path, "r") as f:
                token = f.read().strip()
            if token:
                return StoredCredentials(
                    access_token=token,
                    refresh_token=None,
                    expires_at=None,
                    scopes=list(default_scopes),
                )
        except FileNotFoundError:
            pass

        return None

    def delete(self) -> None:
        """Remove both modern and legacy credential files."""
        for path in (self._credentials_path, self._legacy_token_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
