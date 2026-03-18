"""Claude Code log data models — ported from ClaudeLogModels.swift."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Set


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        return self


# ---------------------------------------------------------------------------
# MessageRecord
# ---------------------------------------------------------------------------

@dataclass
class MessageRecord:
    timestamp: datetime
    model: str
    session_id: str
    usage: TokenUsage


# ---------------------------------------------------------------------------
# ModelStats
# ---------------------------------------------------------------------------

@dataclass
class ModelStats:
    model: str
    message_count: int
    usage: TokenUsage


# ---------------------------------------------------------------------------
# DailyStats
# ---------------------------------------------------------------------------

@dataclass
class DailyStats:
    date: str           # "yyyy-MM-dd"
    display_date: datetime
    message_count: int
    usage: TokenUsage


# ---------------------------------------------------------------------------
# MinuteStats
# ---------------------------------------------------------------------------

@dataclass
class MinuteStats:
    minute: datetime
    tokens: int


# ---------------------------------------------------------------------------
# AggregatedStats
# ---------------------------------------------------------------------------

@dataclass
class AggregatedStats:
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    total_messages: int = 0
    session_ids: Set[str] = field(default_factory=set)
    model_breakdown: List[ModelStats] = field(default_factory=list)
    daily_breakdown: List[DailyStats] = field(default_factory=list)
    today_usage: TokenUsage = field(default_factory=TokenUsage)
    today_messages: int = 0
    last_hour_minutes: List[MinuteStats] = field(default_factory=list)
    estimated_cost: float = 0.0

    @property
    def session_count(self) -> int:
        return len(self.session_ids)


# ---------------------------------------------------------------------------
# CostEstimator
# ---------------------------------------------------------------------------

class CostEstimator:
    """Approximate cost using pattern-matched model pricing."""

    @staticmethod
    def estimate_cost(model: str, usage: TokenUsage) -> float:
        pricing = CostEstimator._pricing_for_model(model)
        input_cost = usage.input / 1_000_000.0 * pricing[0]
        output_cost = usage.output / 1_000_000.0 * pricing[1]
        cache_read_cost = usage.cache_read / 1_000_000.0 * pricing[2]
        cache_write_cost = usage.cache_write / 1_000_000.0 * pricing[3]
        return input_cost + output_cost + cache_read_cost + cache_write_cost

    @staticmethod
    def _pricing_for_model(model: str) -> tuple:
        """Returns (input_per_M, output_per_M, cache_read_per_M, cache_write_per_M)."""
        lowered = model.lower()
        if "opus" in lowered:
            return (15.0, 75.0, 1.5, 18.75)
        elif "haiku" in lowered:
            return (0.25, 1.25, 0.025, 0.30)
        else:
            # Default to Sonnet pricing
            return (3.0, 15.0, 0.3, 3.75)


# ---------------------------------------------------------------------------
# TokenFormatter
# ---------------------------------------------------------------------------

class TokenFormatter:
    """Human-readable formatting for token counts and costs."""

    @staticmethod
    def format(count: int) -> str:
        if count >= 1_000_000_000:
            return f"{count / 1_000_000_000:.1f}B"
        elif count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    @staticmethod
    def format_cost(amount: float) -> str:
        if amount >= 1000:
            return f"${amount:.0f}"
        elif amount >= 100:
            return f"${amount:.1f}"
        return f"${amount:.2f}"
