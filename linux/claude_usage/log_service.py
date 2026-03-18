"""Claude Code JSONL log parser and aggregator — ported from ClaudeLogService.swift."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

from .log_models import (
    AggregatedStats,
    CostEstimator,
    DailyStats,
    MessageRecord,
    MinuteStats,
    ModelStats,
    TokenUsage,
)


# ---------------------------------------------------------------------------
# File cache entry
# ---------------------------------------------------------------------------

@dataclass
class _CachedFile:
    mtime: float
    size: int
    records: List[MessageRecord]


# ---------------------------------------------------------------------------
# ClaudeLogParser
# ---------------------------------------------------------------------------

class ClaudeLogParser:
    """Stateful parser that caches previously-read JSONL files."""

    projects_directory: str = os.path.join(
        os.path.expanduser("~"), ".claude", "projects"
    )

    def __init__(self) -> None:
        self._file_cache: Dict[str, _CachedFile] = {}

    # ------------------------------------------------------------------
    # Date parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_date(s: str) -> Optional[datetime]:
        """Parse an ISO 8601 timestamp string."""
        if not s:
            return None
        normalised = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalised)
        except (ValueError, TypeError):
            pass
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_and_aggregate(self, now: Optional[datetime] = None) -> AggregatedStats:
        """Walk the projects directory, parse JSONL files, and aggregate."""
        if now is None:
            now = datetime.now(timezone.utc)

        projects_dir = self.projects_directory
        if not os.path.isdir(projects_dir):
            return AggregatedStats()

        all_records: List[MessageRecord] = []
        seen_paths: set = set()

        for dirpath, _dirnames, filenames in os.walk(projects_dir):
            for fname in filenames:
                if not fname.endswith(".jsonl"):
                    continue
                full_path = os.path.join(dirpath, fname)
                seen_paths.add(full_path)

                try:
                    stat = os.stat(full_path)
                except OSError:
                    continue
                mtime = stat.st_mtime
                size = stat.st_size

                cached = self._file_cache.get(full_path)
                if cached is not None and cached.mtime == mtime and cached.size == size:
                    all_records.extend(cached.records)
                    continue

                # Parse and cache
                try:
                    with open(full_path, "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                records = self.parse_jsonl_data(data)
                self._file_cache[full_path] = _CachedFile(
                    mtime=mtime, size=size, records=records
                )
                all_records.extend(records)

        # Evict deleted files from cache
        stale = set(self._file_cache.keys()) - seen_paths
        for key in stale:
            del self._file_cache[key]

        return self.aggregate(all_records, now)

    # ------------------------------------------------------------------
    # JSONL parsing
    # ------------------------------------------------------------------

    @classmethod
    def parse_jsonl_data(cls, data: bytes) -> List[MessageRecord]:
        """Parse raw bytes of a JSONL file into MessageRecord entries."""
        if not data:
            return []

        records: List[MessageRecord] = []
        for line in data.split(b"\n"):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(obj, dict):
                continue
            if obj.get("type") != "assistant":
                continue

            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if not model:
                continue
            usage_dict = message.get("usage")
            if not isinstance(usage_dict, dict):
                continue

            session_id = obj.get("sessionId", "")
            timestamp_str = obj.get("timestamp", "")
            timestamp = cls.parse_date(timestamp_str)
            if timestamp is None:
                continue

            usage = TokenUsage(
                input=usage_dict.get("input_tokens", 0),
                output=usage_dict.get("output_tokens", 0),
                cache_read=usage_dict.get("cache_read_input_tokens", 0),
                cache_write=usage_dict.get("cache_creation_input_tokens", 0),
            )

            if usage.total == 0:
                continue

            records.append(MessageRecord(
                timestamp=timestamp,
                model=model,
                session_id=session_id,
                usage=usage,
            ))

        return records

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate(
        records: List[MessageRecord],
        now: Optional[datetime] = None,
    ) -> AggregatedStats:
        if now is None:
            now = datetime.now(timezone.utc)

        stats = AggregatedStats()

        # Use a naive "today start" relative to UTC
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        one_hour_ago = now - timedelta(hours=1)

        model_map: Dict[str, Tuple[int, TokenUsage]] = {}
        day_map: Dict[str, Tuple[int, TokenUsage]] = {}
        minute_map: Dict[datetime, int] = {}

        for record in records:
            stats.total_usage += record.usage
            stats.total_messages += 1
            stats.session_ids.add(record.session_id)
            stats.estimated_cost += CostEstimator.estimate_cost(
                record.model, record.usage
            )

            # Per-model
            entry = model_map.get(record.model, (0, TokenUsage()))
            model_map[record.model] = (
                entry[0] + 1,
                entry[1] + record.usage,
            )

            # Per-day
            day_key = record.timestamp.strftime("%Y-%m-%d")
            day_entry = day_map.get(day_key, (0, TokenUsage()))
            day_map[day_key] = (
                day_entry[0] + 1,
                day_entry[1] + record.usage,
            )

            # Today
            if record.timestamp >= today_start:
                stats.today_usage += record.usage
                stats.today_messages += 1

            # Last hour (per-minute buckets)
            if record.timestamp >= one_hour_ago:
                minute_dt = record.timestamp.replace(second=0, microsecond=0)
                minute_map[minute_dt] = minute_map.get(minute_dt, 0) + record.usage.total

        # Build model breakdown
        stats.model_breakdown = sorted(
            [
                ModelStats(model=model, message_count=count, usage=usage)
                for model, (count, usage) in model_map.items()
            ],
            key=lambda s: s.usage.total,
            reverse=True,
        )

        # Build daily breakdown (14 days)
        stats.daily_breakdown = _build_daily_breakdown(day_map, 14, today_start)

        # Build minute breakdown (60 buckets)
        stats.last_hour_minutes = _build_minute_breakdown(minute_map, now)

        return stats


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_daily_breakdown(
    day_map: Dict[str, Tuple[int, TokenUsage]],
    days: int,
    today_start: datetime,
) -> List[DailyStats]:
    result: List[DailyStats] = []
    for offset in range(days - 1, -1, -1):
        date = today_start - timedelta(days=offset)
        key = date.strftime("%Y-%m-%d")
        entry = day_map.get(key)
        result.append(DailyStats(
            date=key,
            display_date=date,
            message_count=entry[0] if entry else 0,
            usage=entry[1] if entry else TokenUsage(),
        ))
    return result


def _build_minute_breakdown(
    minute_map: Dict[datetime, int],
    now: datetime,
) -> List[MinuteStats]:
    current_minute = now.replace(second=0, microsecond=0)
    result: List[MinuteStats] = []
    for offset in range(59, -1, -1):
        minute = current_minute - timedelta(minutes=offset)
        result.append(MinuteStats(
            minute=minute,
            tokens=minute_map.get(minute, 0),
        ))
    return result
