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

            cache_write = usage_dict.get("cache_creation_input_tokens", 0)

            # "cache_creation" breaks the write total down by TTL. A 1-hour
            # write bills at 2x input vs 1.25x for 5-minute. Absent means all
            # writes are 5-minute.
            cache_write_1h = 0
            creation = usage_dict.get("cache_creation")
            if isinstance(creation, dict):
                cache_write_1h = creation.get("ephemeral_1h_input_tokens", 0)

            usage = TokenUsage(
                input=usage_dict.get("input_tokens", 0),
                output=usage_dict.get("output_tokens", 0),
                cache_read=usage_dict.get("cache_read_input_tokens", 0),
                cache_write=cache_write,
                cache_write_1h=min(cache_write_1h, cache_write),
            )

            if usage.total == 0:
                continue

            # Billable modifiers recorded alongside the token counts.
            web_searches = 0
            server_tools = usage_dict.get("server_tool_use")
            if isinstance(server_tools, dict):
                web_searches = server_tools.get("web_search_requests") or 0

            speed = usage_dict.get("speed")
            geo = usage_dict.get("inference_geo")

            records.append(MessageRecord(
                timestamp=timestamp,
                model=model,
                session_id=session_id,
                usage=usage,
                message_id=message.get("id") or "",
                request_id=obj.get("requestId") or "",
                speed=speed if isinstance(speed, str) else None,
                inference_geo=geo if isinstance(geo, str) else None,
                web_search_requests=web_searches,
            ))

        return records

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def deduplicate(records: List[MessageRecord]) -> List[MessageRecord]:
        """Collapse the repeated rows Claude Code writes for one API response.

        One assistant response is logged as several JSONL lines — one per content
        block (thinking, then each tool_use) — and every line repeats the same
        usage object. Counting all of them inflates tokens, message counts and
        cost by however many blocks the response had.

        Keyed on message ID + request ID, keeping the row with the largest total:
        output_tokens grows across a response's lines while the input and cache
        fields stay fixed, so the largest row is the complete one. Taking the max
        rather than the last also makes this independent of file-walk order,
        which is not guaranteed and can change between refreshes.

        Runs over records from *all* files, since a resumed session can spread
        one response's rows across two transcripts.
        """
        best: Dict[Tuple[str, str], MessageRecord] = {}
        unkeyed: List[MessageRecord] = []

        for record in records:
            # Without a message ID there is nothing safe to group on — keep the
            # row as-is rather than risk collapsing distinct responses.
            if not record.message_id:
                unkeyed.append(record)
                continue
            key = (record.message_id, record.request_id)
            existing = best.get(key)
            if existing is None or record.usage.total > existing.usage.total:
                best[key] = record

        # dicts preserve insertion order, so first-seen order is retained.
        return list(best.values()) + unkeyed

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate(
        records: List[MessageRecord],
        now: Optional[datetime] = None,
    ) -> AggregatedStats:
        # Day and minute buckets are keyed in *local* time so that "Today" and
        # the chart labels match the user's clock, matching the macOS build's
        # use of Calendar.current. Log timestamps are UTC, so bucketing them
        # directly would roll the day over at UTC midnight.
        if now is None:
            now = datetime.now().astimezone()
        else:
            now = now.astimezone()

        stats = AggregatedStats()

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        one_hour_ago = now - timedelta(hours=1)

        model_map: Dict[str, Tuple[int, TokenUsage]] = {}
        day_map: Dict[str, Tuple[int, TokenUsage]] = {}
        minute_map: Dict[datetime, int] = {}

        for record in ClaudeLogParser.deduplicate(records):
            record_cost = CostEstimator.estimate_cost(
                record.model, record.usage, record.billing
            )
            stats.total_usage += record.usage
            stats.total_messages += 1
            stats.session_ids.add(record.session_id)
            stats.estimated_cost += record_cost

            local_ts = record.timestamp.astimezone(now.tzinfo)

            # Per-model
            entry = model_map.get(record.model, (0, TokenUsage()))
            model_map[record.model] = (
                entry[0] + 1,
                entry[1] + record.usage,
            )

            # Per-day
            day_key = local_ts.strftime("%Y-%m-%d")
            day_entry = day_map.get(day_key, (0, TokenUsage()))
            day_map[day_key] = (
                day_entry[0] + 1,
                day_entry[1] + record.usage,
            )

            # Today
            if local_ts >= today_start:
                stats.today_usage += record.usage
                stats.today_messages += 1
                stats.today_cost += record_cost

            # Last hour (per-minute buckets)
            if local_ts >= one_hour_ago:
                minute_dt = local_ts.replace(second=0, microsecond=0)
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
