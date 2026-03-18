"""Usage data models — ported from UsageModel.swift and UsageHistoryModel.swift."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------

_FALLBACK_PATTERNS = [
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
]


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 date string, returning a timezone-aware datetime or None."""
    if not value:
        return None

    # Python's fromisoformat doesn't handle trailing 'Z' before 3.11
    normalised = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        pass

    for pattern in _FALLBACK_PATTERNS:
        try:
            dt = datetime.strptime(value, pattern)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# UsageBucket
# ---------------------------------------------------------------------------

@dataclass
class UsageBucket:
    utilization: Optional[float] = None
    resets_at: Optional[str] = None

    @property
    def resets_at_date(self) -> Optional[datetime]:
        return _parse_iso_date(self.resets_at)

    def reconciled(
        self,
        previous: Optional[UsageBucket] = None,
        reset_interval: float = 0.0,
        now: Optional[datetime] = None,
    ) -> UsageBucket:
        """Carry forward a reset time when the server omits it."""
        if self.resets_at_date is not None:
            return self

        if previous is None:
            return self

        previous_date = previous.resets_at_date
        if previous_date is None:
            return self

        if now is None:
            now = datetime.now(timezone.utc)

        resolved = _next_reset_date(previous_date, reset_interval, now)
        return UsageBucket(
            utilization=self.utilization,
            resets_at=resolved.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )


def _next_reset_date(previous: datetime, reset_interval: float, now: datetime) -> datetime:
    if reset_interval <= 0:
        return previous
    if previous > now:
        return previous
    elapsed = (now - previous).total_seconds()
    step_count = math.floor(elapsed / reset_interval) + 1
    return previous + timedelta(seconds=step_count * reset_interval)


# ---------------------------------------------------------------------------
# ExtraUsage
# ---------------------------------------------------------------------------

@dataclass
class ExtraUsage:
    is_enabled: bool = False
    utilization: Optional[float] = None
    used_credits: Optional[float] = None
    monthly_limit: Optional[float] = None

    @property
    def used_credits_amount(self) -> Optional[float]:
        """API returns credits in minor units (cents); convert to dollars."""
        if self.used_credits is None:
            return None
        return self.used_credits / 100.0

    @property
    def monthly_limit_amount(self) -> Optional[float]:
        if self.monthly_limit is None:
            return None
        return self.monthly_limit / 100.0

    @staticmethod
    def format_usd(amount: float) -> str:
        return f"${amount:,.2f}"


# ---------------------------------------------------------------------------
# UsageResponse
# ---------------------------------------------------------------------------

@dataclass
class UsageResponse:
    five_hour: Optional[UsageBucket] = None
    seven_day: Optional[UsageBucket] = None
    seven_day_opus: Optional[UsageBucket] = None
    seven_day_sonnet: Optional[UsageBucket] = None
    extra_usage: Optional[ExtraUsage] = None

    def reconciled(
        self,
        previous: Optional[UsageResponse] = None,
        now: Optional[datetime] = None,
    ) -> UsageResponse:
        if now is None:
            now = datetime.now(timezone.utc)

        def _reconcile_bucket(
            current: Optional[UsageBucket],
            prev: Optional[UsageBucket],
            interval: float,
        ) -> Optional[UsageBucket]:
            if current is None:
                return None
            return current.reconciled(prev, interval, now)

        return UsageResponse(
            five_hour=_reconcile_bucket(
                self.five_hour,
                previous.five_hour if previous else None,
                5 * 60 * 60,
            ),
            seven_day=_reconcile_bucket(
                self.seven_day,
                previous.seven_day if previous else None,
                7 * 24 * 60 * 60,
            ),
            seven_day_opus=_reconcile_bucket(
                self.seven_day_opus,
                previous.seven_day_opus if previous else None,
                7 * 24 * 60 * 60,
            ),
            seven_day_sonnet=_reconcile_bucket(
                self.seven_day_sonnet,
                previous.seven_day_sonnet if previous else None,
                7 * 24 * 60 * 60,
            ),
            extra_usage=self.extra_usage,
        )

    @classmethod
    def from_dict(cls, data: dict) -> UsageResponse:
        """Parse a dict with snake_case keys into a UsageResponse."""

        def _parse_bucket(d: Optional[dict]) -> Optional[UsageBucket]:
            if d is None:
                return None
            return UsageBucket(
                utilization=d.get("utilization"),
                resets_at=d.get("resets_at"),
            )

        def _parse_extra(d: Optional[dict]) -> Optional[ExtraUsage]:
            if d is None:
                return None
            return ExtraUsage(
                is_enabled=d.get("is_enabled", False),
                utilization=d.get("utilization"),
                used_credits=d.get("used_credits"),
                monthly_limit=d.get("monthly_limit"),
            )

        return cls(
            five_hour=_parse_bucket(data.get("five_hour")),
            seven_day=_parse_bucket(data.get("seven_day")),
            seven_day_opus=_parse_bucket(data.get("seven_day_opus")),
            seven_day_sonnet=_parse_bucket(data.get("seven_day_sonnet")),
            extra_usage=_parse_extra(data.get("extra_usage")),
        )


# ---------------------------------------------------------------------------
# UsageDataPoint / UsageHistory
# ---------------------------------------------------------------------------

@dataclass
class UsageDataPoint:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pct_5h: float = 0.0
    pct_7d: float = 0.0
    pct_sonnet_7d: Optional[float] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "pct_5h": self.pct_5h,
            "pct_7d": self.pct_7d,
        }
        if self.pct_sonnet_7d is not None:
            d["pct_sonnet_7d"] = self.pct_sonnet_7d
        return d

    @classmethod
    def from_dict(cls, data: dict) -> UsageDataPoint:
        ts = _parse_iso_date(data.get("timestamp")) or datetime.now(timezone.utc)
        return cls(
            timestamp=ts,
            pct_5h=data.get("pct_5h", 0.0),
            pct_7d=data.get("pct_7d", 0.0),
            pct_sonnet_7d=data.get("pct_sonnet_7d"),
            id=data.get("id", str(uuid.uuid4())),
        )


@dataclass
class UsageHistory:
    data_points: List[UsageDataPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"dataPoints": [p.to_dict() for p in self.data_points]}

    @classmethod
    def from_dict(cls, data: dict) -> UsageHistory:
        raw = data.get("dataPoints", [])
        return cls(data_points=[UsageDataPoint.from_dict(d) for d in raw])


# ---------------------------------------------------------------------------
# TimeRange
# ---------------------------------------------------------------------------

class TimeRange(Enum):
    HOUR_1 = "1h"
    HOUR_6 = "6h"
    DAY_1 = "1d"
    DAY_7 = "7d"
    DAY_30 = "30d"

    @property
    def interval(self) -> float:
        """Duration of the range in seconds."""
        mapping = {
            "1h": 3600,
            "6h": 6 * 3600,
            "1d": 86400,
            "7d": 7 * 86400,
            "30d": 30 * 86400,
        }
        return float(mapping[self.value])

    @property
    def target_point_count(self) -> int:
        mapping = {
            "1h": 120,
            "6h": 180,
            "1d": 200,
            "7d": 200,
            "30d": 200,
        }
        return mapping[self.value]
