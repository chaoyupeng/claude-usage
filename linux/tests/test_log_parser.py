"""Tests for the Claude Code JSONL parser, dedup, pricing and time bucketing.

Written with stdlib unittest so they run under both `python3 -m unittest` and
the `pytest` target in the Makefile.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from claude_usage.log_models import (
    BillingContext,
    CostEstimator,
    MessageRecord,
    TokenFormatter,
    TokenUsage,
)
from claude_usage.log_service import ClaudeLogParser


def _line(
    *,
    model: str = "claude-opus-5",
    message_id: str = "msg_1",
    request_id: str = "req_1",
    timestamp: str = "2026-07-20T10:00:00.000Z",
    session: str = "s1",
    inp: int = 0,
    out: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    cache_write_1h: int | None = None,
) -> str:
    """Build one assistant JSONL line."""
    usage: dict = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
    }
    if cache_write_1h is not None:
        usage["cache_creation"] = {
            "ephemeral_5m_input_tokens": cache_write - cache_write_1h,
            "ephemeral_1h_input_tokens": cache_write_1h,
        }
    message: dict = {"model": model, "usage": usage}
    if message_id:
        message["id"] = message_id
    import json

    obj: dict = {
        "type": "assistant",
        "message": message,
        "timestamp": timestamp,
        "sessionId": session,
    }
    if request_id:
        obj["requestId"] = request_id
    return json.dumps(obj)


def _parse(*lines: str) -> list[MessageRecord]:
    return ClaudeLogParser.parse_jsonl_data("\n".join(lines).encode())


# Three lines for one API response: a thinking block then two tool_use blocks.
# Input and cache counts are identical; output_tokens grows to its final value.
ONE_RESPONSE_THREE_BLOCKS = (
    _line(out=6, inp=2, cache_read=100, cache_write=50, timestamp="2026-07-20T10:00:00.000Z"),
    _line(out=6, inp=2, cache_read=100, cache_write=50, timestamp="2026-07-20T10:00:01.000Z"),
    _line(out=303, inp=2, cache_read=100, cache_write=50, timestamp="2026-07-20T10:00:02.000Z"),
)


class TestParsing(unittest.TestCase):
    def test_empty_data(self):
        self.assertEqual(ClaudeLogParser.parse_jsonl_data(b""), [])

    def test_non_assistant_rows_skipped(self):
        rows = _parse('{"type":"user","message":{},"timestamp":"2026-07-20T10:00:00Z"}')
        self.assertEqual(rows, [])

    def test_corrupt_line_skipped_others_kept(self):
        rows = _parse(_line(inp=10), "not json!!!", _line(message_id="msg_2", inp=20))
        self.assertEqual(len(rows), 2)

    def test_zero_token_rows_skipped(self):
        self.assertEqual(_parse(_line()), [])

    def test_invalid_timestamp_skipped(self):
        self.assertEqual(_parse(_line(inp=10, timestamp="not-a-date")), [])

    def test_dedup_identifiers_captured(self):
        row = _parse(_line(inp=10))[0]
        self.assertEqual(row.message_id, "msg_1")
        self.assertEqual(row.request_id, "req_1")

    def test_missing_identifiers_default_to_empty(self):
        row = _parse(_line(inp=10, message_id="", request_id=""))[0]
        self.assertEqual(row.message_id, "")
        self.assertEqual(row.request_id, "")


class TestCacheWriteTTL(unittest.TestCase):
    def test_ttl_breakdown_parsed(self):
        row = _parse(_line(inp=1, cache_write=1000, cache_write_1h=300))[0]
        self.assertEqual(row.usage.cache_write, 1000)
        self.assertEqual(row.usage.cache_write_1h, 300)
        self.assertEqual(row.usage.cache_write_5m, 700)

    def test_absent_breakdown_treated_as_five_minute(self):
        row = _parse(_line(inp=1, cache_write=1000))[0]
        self.assertEqual(row.usage.cache_write_1h, 0)
        self.assertEqual(row.usage.cache_write_5m, 1000)

    def test_one_hour_is_subset_of_total(self):
        # cache_write_1h is part of cache_write, not an extra bucket — counting
        # it in `total` would double-count those tokens.
        usage = TokenUsage(input=10, output=20, cache_read=30, cache_write=40, cache_write_1h=40)
        self.assertEqual(usage.total, 100)

    def test_five_minute_never_negative(self):
        self.assertEqual(TokenUsage(cache_write=10, cache_write_1h=40).cache_write_5m, 0)

    def test_addition_sums_one_hour_writes(self):
        total = TokenUsage(cache_write=100, cache_write_1h=40) + TokenUsage(
            cache_write=200, cache_write_1h=60
        )
        self.assertEqual((total.cache_write, total.cache_write_1h, total.cache_write_5m),
                         (300, 100, 200))


class TestDeduplication(unittest.TestCase):
    def test_collapses_repeated_blocks_of_one_response(self):
        deduped = ClaudeLogParser.deduplicate(_parse(*ONE_RESPONSE_THREE_BLOCKS))
        self.assertEqual(len(deduped), 1)
        # The complete row wins: output reached 303 on the final block.
        self.assertEqual(deduped[0].usage.output, 303)
        self.assertEqual(deduped[0].usage.total, 2 + 303 + 100 + 50)

    def test_independent_of_row_order(self):
        # File walk order is not guaranteed and can change between refreshes, so
        # the complete row must win even when it comes first.
        rows = _parse(*ONE_RESPONSE_THREE_BLOCKS)
        forward = ClaudeLogParser.deduplicate(rows)
        backward = ClaudeLogParser.deduplicate(list(reversed(rows)))
        self.assertEqual(forward[0].usage.total, backward[0].usage.total)

    def test_distinct_responses_kept(self):
        rows = _parse(
            _line(message_id="msg_1", request_id="req_1", inp=10),
            _line(message_id="msg_2", request_id="req_2", inp=20),
        )
        self.assertEqual(len(ClaudeLogParser.deduplicate(rows)), 2)

    def test_same_message_id_different_request_id_kept(self):
        rows = _parse(
            _line(message_id="msg_1", request_id="req_1", inp=10),
            _line(message_id="msg_1", request_id="req_2", inp=20),
        )
        self.assertEqual(len(ClaudeLogParser.deduplicate(rows)), 2)

    def test_rows_without_message_id_kept(self):
        # No message ID means nothing safe to group on — keep both rather than
        # collapsing two distinct responses.
        rows = _parse(
            _line(message_id="", request_id="", inp=10, out=1),
            _line(message_id="", request_id="", inp=20, out=2),
        )
        deduped = ClaudeLogParser.deduplicate(rows)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(sum(r.usage.total for r in deduped), 33)

    def test_dedup_spans_files(self):
        # A resumed session can spread one response's rows over two transcripts,
        # so dedup has to span files rather than run per file.
        file_a = _parse(ONE_RESPONSE_THREE_BLOCKS[0])
        file_b = _parse(ONE_RESPONSE_THREE_BLOCKS[2])
        deduped = ClaudeLogParser.deduplicate(file_a + file_b)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].usage.output, 303)

    def test_aggregate_deduplicates_before_counting(self):
        rows = _parse(*ONE_RESPONSE_THREE_BLOCKS)
        now = ClaudeLogParser.parse_date("2026-07-20T10:05:00.000Z")
        stats = ClaudeLogParser.aggregate(rows, now)
        self.assertEqual(stats.total_messages, 1)
        self.assertEqual(stats.total_usage.total, 455)
        self.assertEqual(stats.model_breakdown[0].message_count, 1)


def _billing(
    *,
    when: str = "2026-07-25T00:00:00+00:00",
    speed: str | None = None,
    geo: str | None = None,
    searches: int = 0,
) -> BillingContext:
    return BillingContext(
        timestamp=datetime.fromisoformat(when),
        speed=speed,
        inference_geo=geo,
        web_search_requests=searches,
    )


# After the Sonnet 5 introductory window closes (2026-09-01).
POST_PROMO = _billing(when="2026-09-15T00:00:00+00:00")


class TestPricing(unittest.TestCase):
    ALL_1M = TokenUsage(
        input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000
    )

    def test_published_rates(self):
        """Every rate below is from the published pricing table.

        Cache read is 0.1x input and a 5-minute cache write 1.25x, so an
        all-1M-token fixture totals input + output + 0.1x + 1.25x.
        """
        for model, inp, outp in [
            ("claude-fable-5", 10.0, 50.0),
            ("claude-mythos-5", 10.0, 50.0),
            ("claude-opus-5", 5.0, 25.0),
            ("claude-opus-4-8", 5.0, 25.0),
            ("claude-opus-4-7", 5.0, 25.0),
            ("claude-opus-4-6", 5.0, 25.0),
            ("claude-opus-4-5", 5.0, 25.0),
            ("claude-opus-4-1", 15.0, 75.0),
            ("claude-opus-4-0", 15.0, 75.0),
            ("claude-sonnet-4-6", 3.0, 15.0),
            ("claude-sonnet-4-5", 3.0, 15.0),
            ("claude-haiku-4-5", 1.0, 5.0),
            ("claude-haiku-3-5", 0.80, 4.0),
        ]:
            with self.subTest(model=model):
                expected = inp + outp + inp * 0.1 + inp * 1.25
                self.assertAlmostEqual(
                    CostEstimator.estimate_cost(model, self.ALL_1M, POST_PROMO),
                    expected,
                    places=2,
                )

    def test_opus_4_prefix_does_not_shadow_later_opus_4_x(self):
        # "claude-opus-4" ($15/$75) is a prefix of "claude-opus-4-8" ($5/$25);
        # longest-prefix matching must pick the more specific key.
        usage = TokenUsage(input=1_000_000)
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-4-8", usage, POST_PROMO), 5.0, places=2
        )
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-4-20250514", usage, POST_PROMO), 15.0, places=2
        )

    def test_one_hour_write_costs_more_than_five_minute(self):
        write_5m = TokenUsage(cache_write=1_000_000)
        write_1h = TokenUsage(cache_write=1_000_000, cache_write_1h=1_000_000)
        # Opus input $5 → 5-minute write 1.25x = $6.25, 1-hour write 2x = $10.
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-5", write_5m, POST_PROMO), 6.25, places=2
        )
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-5", write_1h, POST_PROMO), 10.0, places=2
        )

    def test_split_write_bills_both_rates(self):
        usage = TokenUsage(cache_write=1_000_000, cache_write_1h=400_000)
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-5", usage, POST_PROMO),
            0.6 * 6.25 + 0.4 * 10.0,
            places=2,
        )

    def test_dated_model_id_resolves_to_base_model(self):
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-haiku-4-5-20251001", self.ALL_1M, POST_PROMO),
            CostEstimator.estimate_cost("claude-haiku-4-5", self.ALL_1M, POST_PROMO),
            places=4,
        )

    def test_long_context_suffix_resolves_to_base_model(self):
        # 1M-context requests are standard-priced on Claude 4.6 and later.
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-5[1m]", self.ALL_1M, POST_PROMO),
            CostEstimator.estimate_cost("claude-opus-5", self.ALL_1M, POST_PROMO),
            places=4,
        )

    def test_synthetic_model_is_free(self):
        # Claude Code logs "<synthetic>" for locally generated messages.
        self.assertEqual(CostEstimator.estimate_cost("<synthetic>", self.ALL_1M, POST_PROMO), 0.0)

    def test_case_insensitive(self):
        usage = TokenUsage(input=1_000_000)
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("CLAUDE-OPUS-4-8", usage, POST_PROMO), 5.0, places=2
        )

    def test_unknown_model_falls_back_to_tier(self):
        usage = TokenUsage(input=1_000_000)
        for model, expected in [
            ("claude-opus-9-9", 5.0),
            ("claude-haiku-9-9", 1.0),
            ("claude-mythos-9", 10.0),
            ("claude-4-ultra", 3.0),  # Sonnet tier
        ]:
            with self.subTest(model=model):
                self.assertAlmostEqual(
                    CostEstimator.estimate_cost(model, usage, POST_PROMO), expected, places=2
                )

    def test_zero_usage_is_free(self):
        self.assertEqual(
            CostEstimator.estimate_cost("claude-opus-5", TokenUsage(), POST_PROMO), 0.0
        )


class TestSonnet5IntroductoryPricing(unittest.TestCase):
    """Sonnet 5 bills $2/$10 through 2026-08-31, then $3/$15.

    Cost therefore depends on each message's own timestamp, not on today's date.
    """

    USAGE = TokenUsage(input=1_000_000, output=1_000_000)

    def test_during_promo(self):
        cost = CostEstimator.estimate_cost("claude-sonnet-5", self.USAGE, _billing())
        self.assertAlmostEqual(cost, 2.0 + 10.0, places=2)

    def test_after_promo(self):
        cost = CostEstimator.estimate_cost("claude-sonnet-5", self.USAGE, POST_PROMO)
        self.assertAlmostEqual(cost, 3.0 + 15.0, places=2)

    def test_last_moment_of_promo(self):
        cost = CostEstimator.estimate_cost(
            "claude-sonnet-5", self.USAGE, _billing(when="2026-08-31T23:59:59+00:00")
        )
        self.assertAlmostEqual(cost, 12.0, places=2)

    def test_first_moment_of_standard_pricing(self):
        cost = CostEstimator.estimate_cost(
            "claude-sonnet-5", self.USAGE, _billing(when="2026-09-01T00:00:00+00:00")
        )
        self.assertAlmostEqual(cost, 18.0, places=2)

    def test_promo_cache_rates_scale_with_promo_input_rate(self):
        # $2 input → read $0.20, 5-min write $2.50, 1-hour write $4.
        usage = TokenUsage(cache_read=1_000_000, cache_write=1_000_000, cache_write_1h=500_000)
        cost = CostEstimator.estimate_cost("claude-sonnet-5", usage, _billing())
        self.assertAlmostEqual(cost, 0.20 + 0.5 * 2.50 + 0.5 * 4.0, places=2)

    def test_promo_does_not_affect_other_models(self):
        during = CostEstimator.estimate_cost("claude-sonnet-4-6", self.USAGE, _billing())
        after = CostEstimator.estimate_cost("claude-sonnet-4-6", self.USAGE, POST_PROMO)
        self.assertAlmostEqual(during, after, places=4)
        self.assertAlmostEqual(during, 18.0, places=2)

    def test_naive_timestamp_still_resolves(self):
        billing = BillingContext(timestamp=datetime(2026, 7, 25, 12, 0, 0))
        cost = CostEstimator.estimate_cost("claude-sonnet-5", self.USAGE, billing)
        self.assertAlmostEqual(cost, 12.0, places=2)


class TestBillingModifiers(unittest.TestCase):
    USAGE = TokenUsage(input=1_000_000, output=1_000_000)

    def test_fast_mode_premium_on_supported_models(self):
        for model in ("claude-opus-5", "claude-opus-4-8"):
            with self.subTest(model=model):
                standard = CostEstimator.estimate_cost(
                    model, self.USAGE, _billing(speed="standard")
                )
                fast = CostEstimator.estimate_cost(model, self.USAGE, _billing(speed="fast"))
                self.assertAlmostEqual(standard, 30.0, places=2)  # $5 + $25
                self.assertAlmostEqual(fast, 60.0, places=2)  # $10 + $50

    def test_fast_mode_ignored_on_unsupported_models(self):
        # Fast mode is not offered on Opus 4.7 or Sonnet, so a stray "fast" must
        # not inflate their cost.
        for model in ("claude-opus-4-7", "claude-sonnet-4-6"):
            with self.subTest(model=model):
                self.assertAlmostEqual(
                    CostEstimator.estimate_cost(model, self.USAGE, _billing(speed="fast")),
                    CostEstimator.estimate_cost(model, self.USAGE, _billing(speed="standard")),
                    places=4,
                )

    def test_missing_speed_is_standard(self):
        self.assertAlmostEqual(
            CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing(speed=None)),
            30.0,
            places=2,
        )

    def test_us_data_residency_multiplier(self):
        base = CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing())
        us = CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing(geo="us"))
        self.assertAlmostEqual(us, base * 1.1, places=4)

    def test_non_us_geo_is_standard_priced(self):
        base = CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing())
        for geo in ("global", "not_available", None):
            with self.subTest(geo=geo):
                self.assertAlmostEqual(
                    CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing(geo=geo)),
                    base,
                    places=4,
                )

    def test_web_search_billed_per_search(self):
        # $10 per 1,000 searches.
        base = CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing())
        with_searches = CostEstimator.estimate_cost(
            "claude-opus-5", self.USAGE, _billing(searches=25)
        )
        self.assertAlmostEqual(with_searches - base, 0.25, places=4)

    def test_search_charges_not_scaled_by_data_residency(self):
        # The 1.1x multiplier applies to token categories, not per-search fees.
        tokens_only = CostEstimator.estimate_cost("claude-opus-5", self.USAGE, _billing(geo="us"))
        with_search = CostEstimator.estimate_cost(
            "claude-opus-5", self.USAGE, _billing(geo="us", searches=10)
        )
        self.assertAlmostEqual(with_search - tokens_only, 0.10, places=4)

    def test_fast_mode_and_residency_stack(self):
        cost = CostEstimator.estimate_cost(
            "claude-opus-5", self.USAGE, _billing(speed="fast", geo="us")
        )
        self.assertAlmostEqual(cost, 60.0 * 1.1, places=2)

    def test_modifiers_parsed_from_log_line(self):
        import json

        line = json.dumps({
            "type": "assistant",
            "requestId": "r",
            "timestamp": "2026-07-20T10:00:00.000Z",
            "sessionId": "s1",
            "message": {
                "id": "m",
                "model": "claude-opus-5",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 1,
                    "speed": "fast",
                    "inference_geo": "us",
                    "server_tool_use": {"web_search_requests": 3},
                },
            },
        })
        row = ClaudeLogParser.parse_jsonl_data(line.encode())[0]
        self.assertEqual(row.speed, "fast")
        self.assertEqual(row.inference_geo, "us")
        self.assertEqual(row.web_search_requests, 3)
        self.assertEqual(row.billing.speed, "fast")

    def test_aggregate_applies_modifiers(self):
        now = datetime.now().astimezone()
        rows = [
            MessageRecord(
                now, "claude-opus-5", "s1", TokenUsage(input=1_000_000),
                "m1", "r1", speed="fast",
            )
        ]
        stats = ClaudeLogParser.aggregate(rows, now)
        # Fast mode input is $10/MTok rather than $5.
        self.assertAlmostEqual(stats.estimated_cost, 10.0, places=2)


class TestLocalTimeBucketing(unittest.TestCase):
    """Day and minute buckets must key off local time, not UTC.

    A UTC-keyed day rolls over mid-morning for UTC+10 users, so "Today" and the
    14-day chart would be attributed to the wrong day.
    """

    def _record(self, ts: datetime) -> MessageRecord:
        return MessageRecord(
            timestamp=ts,
            model="claude-opus-5",
            session_id="s1",
            usage=TokenUsage(input=100),
            message_id=f"msg_{ts.isoformat()}",
            request_id="req",
        )

    def test_today_uses_local_midnight(self):
        # 23:00 local "today" is already tomorrow in UTC for a UTC+10 zone, and
        # vice versa — anchor on a local now and check the local day matches.
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        this_morning = local_now.replace(hour=1)
        stats = ClaudeLogParser.aggregate([self._record(this_morning)], local_now)
        self.assertEqual(stats.today_messages, 1)
        self.assertEqual(stats.today_usage.input, 100)

    def test_yesterday_excluded_from_today(self):
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        yesterday = local_now - timedelta(days=1)
        stats = ClaudeLogParser.aggregate([self._record(yesterday)], local_now)
        self.assertEqual(stats.total_messages, 1)
        self.assertEqual(stats.today_messages, 0)

    def test_day_key_matches_local_date(self):
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        stats = ClaudeLogParser.aggregate([self._record(local_now)], local_now)
        today_key = local_now.strftime("%Y-%m-%d")
        matching = [d for d in stats.daily_breakdown if d.date == today_key]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].message_count, 1)

    def test_utc_timestamp_bucketed_into_local_day(self):
        # The record is given in UTC, as the logs store it; it must land in the
        # local day that contains it.
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        utc_ts = local_now.astimezone(timezone.utc)
        stats = ClaudeLogParser.aggregate([self._record(utc_ts)], local_now)
        self.assertEqual(stats.today_messages, 1)

    def test_minute_bucket_uses_local_clock(self):
        # Matters for half-hour-offset zones (e.g. UTC+9:30), where the
        # minute-of-hour differs between UTC and local time.
        local_now = datetime.now().astimezone().replace(second=0, microsecond=0)
        five_min_ago = local_now - timedelta(minutes=5)
        stats = ClaudeLogParser.aggregate([self._record(five_min_ago)], local_now)
        non_zero = [m for m in stats.last_hour_minutes if m.tokens > 0]
        self.assertEqual(len(non_zero), 1)
        self.assertEqual(non_zero[0].tokens, 100)
        self.assertEqual(non_zero[0].minute.minute, five_min_ago.minute)

    def test_naive_timestamp_does_not_crash(self):
        # Defensive: a timestamp without a zone is treated as local rather than
        # raising on the aware/naive comparison.
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        naive = local_now.replace(tzinfo=None).replace(hour=1)
        stats = ClaudeLogParser.aggregate([self._record(naive)], local_now)
        self.assertEqual(stats.total_messages, 1)


class TestTodayCost(unittest.TestCase):
    def test_today_cost_uses_each_message_own_model_rate(self):
        # Today: 1M Fable input ($10). Yesterday: 1M Sonnet 4.6 input ($3).
        # Prorating total cost by token share would give $6.50 for today, since
        # the two days have equal token counts. The real figure is $10.
        # Sonnet 4.6 rather than Sonnet 5 keeps this independent of the Sonnet 5
        # promotional window.
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            MessageRecord(local_now, "claude-fable-5", "s1", TokenUsage(input=1_000_000), "m1", "r1"),
            MessageRecord(
                local_now - timedelta(days=1),
                "claude-sonnet-4-6", "s1", TokenUsage(input=1_000_000), "m2", "r2",
            ),
        ]
        stats = ClaudeLogParser.aggregate(rows, local_now)
        self.assertAlmostEqual(stats.estimated_cost, 13.0, places=2)
        self.assertAlmostEqual(stats.today_cost, 10.0, places=2)
        prorated = stats.estimated_cost * stats.today_usage.total / stats.total_usage.total
        self.assertAlmostEqual(prorated, 6.5, places=2)  # what the old code showed

    def test_today_cost_zero_when_nothing_today(self):
        local_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            MessageRecord(
                local_now - timedelta(days=3),
                "claude-opus-5", "s1", TokenUsage(input=1_000_000), "m1", "r1",
            )
        ]
        stats = ClaudeLogParser.aggregate(rows, local_now)
        self.assertEqual(stats.today_cost, 0.0)
        self.assertGreater(stats.estimated_cost, 0.0)


class TestCostFormatting(unittest.TestCase):
    """Mirrors the Swift TokenFormatter tests so both ports render identically."""

    def test_rounds_halves_up_not_to_even(self):
        # Both Python's format spec and C printf round halves to even, which
        # would render these one cent/dollar low.
        self.assertEqual(TokenFormatter.format_cost(2100.5), "$2101")
        self.assertEqual(TokenFormatter.format_cost(2102.5), "$2103")

    def test_precision_tiers(self):
        self.assertEqual(TokenFormatter.format_cost(0.0), "$0.00")
        self.assertEqual(TokenFormatter.format_cost(1.50), "$1.50")
        self.assertEqual(TokenFormatter.format_cost(99.99), "$99.99")
        self.assertEqual(TokenFormatter.format_cost(100.0), "$100.0")
        self.assertEqual(TokenFormatter.format_cost(999.9), "$999.9")
        self.assertEqual(TokenFormatter.format_cost(1000.0), "$1000")

    def test_token_counts(self):
        self.assertEqual(TokenFormatter.format(0), "0")
        self.assertEqual(TokenFormatter.format(999), "999")
        self.assertEqual(TokenFormatter.format(12345), "12.3K")
        self.assertEqual(TokenFormatter.format(1_000_000), "1.0M")
        self.assertEqual(TokenFormatter.format(2_800_000_000), "2.8B")


class TestAggregateShape(unittest.TestCase):
    def test_empty_records(self):
        stats = ClaudeLogParser.aggregate([])
        self.assertEqual(stats.total_messages, 0)
        self.assertEqual(stats.estimated_cost, 0.0)
        self.assertEqual(len(stats.daily_breakdown), 14)
        self.assertEqual(len(stats.last_hour_minutes), 60)

    def test_sessions_counted_distinctly(self):
        now = datetime.now().astimezone()
        rows = [
            MessageRecord(now, "claude-opus-5", "s1", TokenUsage(input=10), "m1", "r1"),
            MessageRecord(now, "claude-opus-5", "s2", TokenUsage(input=10), "m2", "r2"),
            MessageRecord(now, "claude-opus-5", "s1", TokenUsage(input=10), "m3", "r3"),
        ]
        self.assertEqual(ClaudeLogParser.aggregate(rows, now).session_count, 2)

    def test_model_breakdown_sorted_by_tokens_descending(self):
        now = datetime.now().astimezone()
        rows = [
            MessageRecord(now, "claude-sonnet-5", "s1", TokenUsage(input=10), "m1", "r1"),
            MessageRecord(now, "claude-opus-5", "s1", TokenUsage(input=500), "m2", "r2"),
        ]
        breakdown = ClaudeLogParser.aggregate(rows, now).model_breakdown
        self.assertEqual([m.model for m in breakdown], ["claude-opus-5", "claude-sonnet-5"])


if __name__ == "__main__":
    unittest.main()
