"""Usage history persistence and downsampling — ported from UsageHistoryService.swift."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from .models import TimeRange, UsageDataPoint, UsageHistory


class UsageHistoryService:
    """Persists usage data points to disk and provides time-range downsampling."""

    _RETENTION_SECONDS: float = 30 * 86400  # 30 days
    _FLUSH_INTERVAL: float = 300  # 5 minutes (advisory — caller schedules)

    def __init__(self, history_file: Optional[str] = None) -> None:
        if history_file is None:
            config_dir = os.path.join(
                os.path.expanduser("~"), ".config", "claude-usage-bar"
            )
            os.makedirs(config_dir, mode=0o700, exist_ok=True)
            history_file = os.path.join(config_dir, "history.json")
        self._history_file = history_file
        self.history = UsageHistory()
        self._is_dirty = False

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_history(self) -> None:
        if not os.path.isfile(self._history_file):
            return
        try:
            with open(self._history_file, "r") as f:
                data = json.load(f)
            loaded = UsageHistory.from_dict(data)
            loaded.data_points = self._pruned(loaded.data_points)
            self.history = loaded
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            # Corrupt — rename to .bak and start fresh
            backup = self._history_file.rsplit(".", 1)[0] + ".bak.json"
            try:
                os.replace(self._history_file, backup)
            except OSError:
                pass
            self.history = UsageHistory()

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record_data_point(
        self,
        pct_5h: float,
        pct_7d: float,
        pct_sonnet_7d: Optional[float] = None,
    ) -> None:
        point = UsageDataPoint(
            pct_5h=pct_5h,
            pct_7d=pct_7d,
            pct_sonnet_7d=pct_sonnet_7d,
        )
        self.history.data_points.append(point)
        self._is_dirty = True

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def flush_to_disk(self) -> None:
        if not self._is_dirty:
            return
        self.history.data_points = self._pruned(self.history.data_points)
        try:
            data = json.dumps(self.history.to_dict(), indent=2)
            tmp_path = self._history_file + ".tmp"
            with open(tmp_path, "w") as f:
                f.write(data)
            os.replace(tmp_path, self._history_file)
        except OSError:
            pass
        self._is_dirty = False

    # ------------------------------------------------------------------
    # Downsampling
    # ------------------------------------------------------------------

    def downsampled_points(self, time_range: TimeRange) -> List[UsageDataPoint]:
        all_points = self.history.data_points
        if len(all_points) <= time_range.target_point_count:
            return list(all_points)

        now = datetime.now(timezone.utc)
        range_start = now - timedelta(seconds=time_range.interval)
        bucket_count = time_range.target_point_count
        bucket_duration = time_range.interval / bucket_count

        buckets: List[List[UsageDataPoint]] = [[] for _ in range(bucket_count)]

        for point in all_points:
            offset = (point.timestamp - range_start).total_seconds()
            idx = int(offset / bucket_duration)
            idx = max(0, min(idx, bucket_count - 1))
            buckets[idx].append(point)

        result: List[UsageDataPoint] = []
        for bucket in buckets:
            if not bucket:
                continue
            n = len(bucket)
            avg_5h = sum(p.pct_5h for p in bucket) / n
            avg_7d = sum(p.pct_7d for p in bucket) / n
            sonnet_vals = [p.pct_sonnet_7d for p in bucket if p.pct_sonnet_7d is not None]
            avg_sonnet: Optional[float] = None
            if sonnet_vals:
                avg_sonnet = sum(sonnet_vals) / len(sonnet_vals)
            avg_ts = sum(p.timestamp.timestamp() for p in bucket) / n
            result.append(UsageDataPoint(
                timestamp=datetime.fromtimestamp(avg_ts, tz=timezone.utc),
                pct_5h=avg_5h,
                pct_7d=avg_7d,
                pct_sonnet_7d=avg_sonnet,
            ))
        return result

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def _pruned(self, points: List[UsageDataPoint]) -> List[UsageDataPoint]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._RETENTION_SECONDS)
        return [p for p in points if p.timestamp >= cutoff]
