"""Claude Code log data models — ported from ClaudeLogModels.swift."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    # Portion of cache_write written with a 1-hour TTL, which bills at 2x the
    # input rate instead of 1.25x. This is a *subset* of cache_write, so it is
    # never added into `total` — it only splits the write for pricing.
    cache_write_1h: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    @property
    def cache_write_5m(self) -> int:
        """Cache writes billed at the 5-minute rate (everything not 1-hour)."""
        return max(self.cache_write - self.cache_write_1h, 0)

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            cache_write_1h=self.cache_write_1h + other.cache_write_1h,
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.cache_write_1h += other.cache_write_1h
        return self


# ---------------------------------------------------------------------------
# MessageRecord
# ---------------------------------------------------------------------------

@dataclass
class BillingContext:
    """Everything other than token counts that affects what a response cost."""

    # When the request was made. Promotional rates are date-gated, so cost has
    # to be evaluated against the message's own timestamp, not "now".
    timestamp: datetime
    # usage.speed; "fast" bills Opus 5 / Opus 4.8 at the premium tier.
    speed: Optional[str] = None
    # usage.inference_geo; "us" applies a 1.1x multiplier to every token
    # category. "global", "not_available" and None are standard-priced.
    inference_geo: Optional[str] = None
    # usage.server_tool_use.web_search_requests; charged per search on top of
    # tokens.
    web_search_requests: int = 0


@dataclass
class MessageRecord:
    timestamp: datetime
    model: str
    session_id: str
    usage: TokenUsage
    # Claude Code writes one JSONL line per content block of a single API
    # response, each repeating that response's usage. These two fields identify
    # the response so the repeats can be collapsed.
    message_id: str = ""
    request_id: str = ""
    # usage.speed — "fast" bills at the fast-mode premium.
    speed: Optional[str] = None
    # usage.inference_geo — "us" adds a data-residency multiplier.
    inference_geo: Optional[str] = None
    # usage.server_tool_use.web_search_requests — billed per search.
    web_search_requests: int = 0

    @property
    def billing(self) -> BillingContext:
        """Non-token inputs to this response's price."""
        return BillingContext(
            timestamp=self.timestamp,
            speed=self.speed,
            inference_geo=self.inference_geo,
            web_search_requests=self.web_search_requests,
        )


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
    # Today's cost, summed per message at that message's own model rate.
    # Prorating estimated_cost by token share instead would assume every token
    # cost the same, which is wrong whenever models are mixed.
    today_cost: float = 0.0

    @property
    def session_count(self) -> int:
        return len(self.session_ids)


# ---------------------------------------------------------------------------
# CostEstimator
# ---------------------------------------------------------------------------

class CostEstimator:
    """Estimates API cost from published per-model rates."""

    # Published input/output price in USD per million tokens, per model.
    #
    # Keys are matched exact-first then longest-prefix, so "claude-opus-4"
    # covers dated IDs like "claude-opus-4-20250514" without shadowing the
    # longer "claude-opus-4-8".
    #
    # Long-context (1M) requests are standard-priced on Claude 4.6 and later, so
    # the "[1m]" model-ID suffix needs no special handling.
    _BASE_RATES = {
        "claude-fable-5": (10.0, 50.0),
        "claude-mythos-5": (10.0, 50.0),
        "claude-opus-5": (5.0, 25.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-opus-4-7": (5.0, 25.0),
        "claude-opus-4-6": (5.0, 25.0),
        "claude-opus-4-5": (5.0, 25.0),
        "claude-opus-4-1": (15.0, 75.0),
        "claude-opus-4": (15.0, 75.0),
        "claude-sonnet-5": (3.0, 15.0),  # promotional rate applied below
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-sonnet-4-5": (3.0, 15.0),
        "claude-sonnet-4": (3.0, 15.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "claude-haiku-3-5": (0.80, 4.0),
    }

    # Cache rates are fixed multiples of the model's input rate rather than
    # separate per-model constants. Verified against every row of the published
    # table.
    _CACHE_READ_MULT = 0.10
    _CACHE_WRITE_5M_MULT = 1.25
    _CACHE_WRITE_1H_MULT = 2.0

    # Sonnet 5 introductory pricing ($2/$10) runs through 2026-08-31; standard
    # pricing ($3/$15) starts 2026-09-01. Boundary taken as UTC midnight — the
    # published date carries no zone, so a few hours either side is possible.
    _SONNET_5_PROMO_RATE = (2.0, 10.0)
    _SONNET_5_PROMO_END = datetime(2026, 9, 1, tzinfo=timezone.utc)

    # Fast mode bills Opus 5 / Opus 4.8 at a flat premium across the whole
    # context window. It is unavailable on other models.
    _FAST_MODE_RATE = (10.0, 50.0)
    _FAST_MODE_MODELS = frozenset({"claude-opus-5", "claude-opus-4-8"})

    # inference_geo "us" multiplies every token category by 1.1.
    _US_DATA_RESIDENCY_MULT = 1.10

    # Web search is billed at $10 per 1,000 searches.
    _COST_PER_WEB_SEARCH = 0.01

    @staticmethod
    def estimate_cost(
        model: str, usage: TokenUsage, billing: Optional[BillingContext] = None
    ) -> float:
        """Estimated API cost for one response, in USD."""
        if billing is None:
            # No billing context: price at standard rates with no modifiers.
            # Uses the promo-era timestamp so Sonnet 5 is not silently
            # mispriced when a caller omits context.
            billing = BillingContext(timestamp=datetime.now(timezone.utc))

        rate = CostEstimator._rate_for(model, billing)
        if rate is None:
            return 0.0
        input_rate, output_rate = rate

        token_cost = (
            usage.input / 1_000_000.0 * input_rate
            + usage.output / 1_000_000.0 * output_rate
            + usage.cache_read / 1_000_000.0 * input_rate * CostEstimator._CACHE_READ_MULT
            + usage.cache_write_5m / 1_000_000.0 * input_rate * CostEstimator._CACHE_WRITE_5M_MULT
            + usage.cache_write_1h / 1_000_000.0 * input_rate * CostEstimator._CACHE_WRITE_1H_MULT
        )

        # Data residency scales token pricing only, not per-search charges.
        residency = (
            CostEstimator._US_DATA_RESIDENCY_MULT
            if (billing.inference_geo or "").lower() == "us"
            else 1.0
        )
        search_cost = billing.web_search_requests * CostEstimator._COST_PER_WEB_SEARCH

        return token_cost * residency + search_cost

    @staticmethod
    def _rate_for(model: str, billing: BillingContext) -> Optional[Tuple[float, float]]:
        """Rate in effect for this model at this point in time.

        Returns None for entries that were never billed as API calls.
        """
        lowered = model.lower()

        # Claude Code logs "<synthetic>" for messages it generated locally.
        if lowered == "<synthetic>":
            return None

        entry = CostEstimator._base_entry(lowered)
        if entry is None:
            return CostEstimator._fallback_rate(lowered)
        matched_key, base_rate = entry

        # Fast mode replaces the base rate outright where it is supported.
        if (billing.speed or "").lower() == "fast" and matched_key in CostEstimator._FAST_MODE_MODELS:
            return CostEstimator._FAST_MODE_RATE

        if matched_key == "claude-sonnet-5":
            ts = billing.timestamp
            if ts.tzinfo is None:
                ts = ts.astimezone()
            if ts < CostEstimator._SONNET_5_PROMO_END:
                return CostEstimator._SONNET_5_PROMO_RATE

        return base_rate

    @staticmethod
    def _base_entry(lowered: str) -> Optional[Tuple[str, Tuple[float, float]]]:
        """Longest-prefix lookup, returning the matched key too.

        Callers need the key to apply model-specific rules without re-deriving
        which model matched.
        """
        exact = CostEstimator._BASE_RATES.get(lowered)
        if exact is not None:
            return (lowered, exact)
        prefixes = [k for k in CostEstimator._BASE_RATES if lowered.startswith(k)]
        if not prefixes:
            return None
        key = max(prefixes, key=len)
        return (key, CostEstimator._BASE_RATES[key])

    @staticmethod
    def _fallback_rate(lowered: str) -> Tuple[float, float]:
        """Tier guess for a model ID with no published rate.

        Covers an unreleased model, or one retired long enough to have been
        dropped from the pricing page (Opus 3, Sonnet 3.x, Haiku 3, Claude 2.x).
        Assumes current-generation pricing for the family; none of those models
        can appear in Claude Code logs, so this is a forward-looking guess
        rather than a historical one.
        """
        if "fable" in lowered or "mythos" in lowered:
            return (10.0, 50.0)
        elif "opus" in lowered:
            return (5.0, 25.0)
        elif "haiku" in lowered:
            return (1.0, 5.0)
        return (3.0, 15.0)  # Sonnet tier


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
        # Python's format spec rounds halves to even, so ".0f" renders 2100.5 as
        # "$2100". Money conventionally rounds halves up, so round to the
        # displayed precision first and format an already-rounded value.
        if amount >= 1000:
            return f"${TokenFormatter._round_half_up(amount, 0):.0f}"
        elif amount >= 100:
            return f"${TokenFormatter._round_half_up(amount, 1):.1f}"
        return f"${TokenFormatter._round_half_up(amount, 2):.2f}"

    @staticmethod
    def _round_half_up(value: float, places: int) -> float:
        """Round to `places` decimals, breaking ties away from zero."""
        quantum = Decimal(1).scaleb(-places)
        return float(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))
