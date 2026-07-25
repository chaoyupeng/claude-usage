import XCTest
@testable import ClaudeUsageBar

final class ClaudeLogModelsTests: XCTestCase {

    // MARK: - TokenUsage

    func testTokenUsageTotalSumsAllFields() {
        let usage = TokenUsage(input: 10, output: 20, cacheRead: 30, cacheWrite: 40)
        XCTAssertEqual(usage.total, 100)
    }

    func testTokenUsageTotalIsZeroWhenEmpty() {
        let usage = TokenUsage()
        XCTAssertEqual(usage.total, 0)
    }

    func testTokenUsageAddition() {
        let a = TokenUsage(input: 1, output: 2, cacheRead: 3, cacheWrite: 4)
        let b = TokenUsage(input: 10, output: 20, cacheRead: 30, cacheWrite: 40)
        let sum = a + b
        XCTAssertEqual(sum.input, 11)
        XCTAssertEqual(sum.output, 22)
        XCTAssertEqual(sum.cacheRead, 33)
        XCTAssertEqual(sum.cacheWrite, 44)
    }

    func testTokenUsagePlusEqualsOperator() {
        var usage = TokenUsage(input: 5, output: 5, cacheRead: 5, cacheWrite: 5)
        usage += TokenUsage(input: 1, output: 2, cacheRead: 3, cacheWrite: 4)
        XCTAssertEqual(usage.input, 6)
        XCTAssertEqual(usage.output, 7)
        XCTAssertEqual(usage.cacheRead, 8)
        XCTAssertEqual(usage.cacheWrite, 9)
    }

    func testTokenUsageAdditionWithZero() {
        let usage = TokenUsage(input: 10, output: 20, cacheRead: 30, cacheWrite: 40)
        let sum = usage + TokenUsage()
        XCTAssertEqual(sum.total, 100)
    }

    func testTokenUsageTotalExcludesOneHourWriteSubset() {
        // cacheWrite1h is part of cacheWrite, not an additional bucket — adding
        // it into `total` would double-count those tokens.
        let usage = TokenUsage(input: 10, output: 20, cacheRead: 30, cacheWrite: 40, cacheWrite1h: 40)
        XCTAssertEqual(usage.total, 100)
    }

    func testTokenUsageFiveMinuteWriteIsRemainder() {
        let usage = TokenUsage(cacheWrite: 100, cacheWrite1h: 30)
        XCTAssertEqual(usage.cacheWrite5m, 70)
    }

    func testTokenUsageFiveMinuteWriteNeverNegative() {
        let usage = TokenUsage(cacheWrite: 10, cacheWrite1h: 40)
        XCTAssertEqual(usage.cacheWrite5m, 0)
    }

    func testTokenUsageAdditionSumsOneHourWrites() {
        let a = TokenUsage(cacheWrite: 100, cacheWrite1h: 40)
        let b = TokenUsage(cacheWrite: 200, cacheWrite1h: 60)
        let sum = a + b
        XCTAssertEqual(sum.cacheWrite, 300)
        XCTAssertEqual(sum.cacheWrite1h, 100)
        XCTAssertEqual(sum.cacheWrite5m, 200)
    }

    // MARK: - CostEstimator

    // All-1M-tokens fixture: makes each rate directly readable off the total.
    private let all1M = TokenUsage(
        input: 1_000_000, output: 1_000_000, cacheRead: 1_000_000, cacheWrite: 1_000_000
    )

    private func billing(
        when iso: String = "2026-07-25T00:00:00Z",
        speed: String? = nil,
        geo: String? = nil,
        searches: Int = 0
    ) -> BillingContext {
        BillingContext(
            timestamp: ClaudeLogParser.parseDate(iso)!,
            speed: speed,
            inferenceGeo: geo,
            webSearchRequests: searches
        )
    }

    /// After the Sonnet 5 introductory window closes (2026-09-01).
    private var postPromo: BillingContext { billing(when: "2026-09-15T00:00:00Z") }

    func testCostEstimatorPublishedRates() {
        // Every rate below is from the published pricing table. Cache read is
        // 0.1x input and a 5-minute cache write 1.25x, so the all-1M fixture
        // totals input + output + 0.1x + 1.25x.
        let cases: [(model: String, input: Double, output: Double)] = [
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
            // Real Haiku 3.5 IDs are generation-first. Asserting on a
            // family-first spelling would exercise a key no log can produce.
            ("claude-3-5-haiku-20241022", 0.80, 4.0),
        ]
        for c in cases {
            let expected = c.input + c.output + c.input * 0.1 + c.input * 1.25
            let actual = CostEstimator.estimateCost(model: c.model, usage: all1M, billing: postPromo)
            XCTAssertEqual(actual, expected, accuracy: 0.01, c.model)
        }
    }

    func testCostEstimatorOpusFourPrefixDoesNotShadowLaterVersions() {
        // "claude-opus-4" ($15/$75) is a prefix of "claude-opus-4-8" ($5/$25);
        // longest-prefix matching must pick the more specific key.
        let usage = TokenUsage(input: 1_000_000)
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-opus-4-8", usage: usage, billing: postPromo),
            5.0, accuracy: 0.01
        )
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-opus-4-20250514", usage: usage, billing: postPromo),
            15.0, accuracy: 0.01
        )
    }

    func testCostEstimatorOneHourCacheWriteCostsMoreThanFiveMinute() {
        let write5m = TokenUsage(cacheWrite: 1_000_000, cacheWrite1h: 0)
        let write1h = TokenUsage(cacheWrite: 1_000_000, cacheWrite1h: 1_000_000)
        // Opus input is $5 → 5-min write 1.25x = $6.25, 1-hour write 2x = $10.
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-opus-5", usage: write5m, billing: postPromo),
            6.25, accuracy: 0.01
        )
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-opus-5", usage: write1h, billing: postPromo),
            10.0, accuracy: 0.01
        )
    }

    func testCostEstimatorSplitCacheWriteBillsBothRates() {
        // 600K at the 5-min rate + 400K at the 1-hour rate.
        let usage = TokenUsage(cacheWrite: 1_000_000, cacheWrite1h: 400_000)
        let cost = CostEstimator.estimateCost(model: "claude-opus-5", usage: usage, billing: postPromo)
        XCTAssertEqual(cost, 0.6 * 6.25 + 0.4 * 10.0, accuracy: 0.01)
    }

    func testCostEstimatorMissingTTLBreakdownTreatedAsFiveMinute() {
        let usage = TokenUsage(cacheWrite: 1_000_000)
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-opus-5", usage: usage, billing: postPromo),
            6.25, accuracy: 0.01
        )
    }

    func testCostEstimatorDatedModelIDResolvesToBaseModel() {
        let dated = CostEstimator.estimateCost(model: "claude-haiku-4-5-20251001", usage: all1M, billing: postPromo)
        let base = CostEstimator.estimateCost(model: "claude-haiku-4-5", usage: all1M, billing: postPromo)
        XCTAssertEqual(dated, base, accuracy: 0.001)
    }

    func testCostEstimatorLongContextSuffixResolvesToBaseModel() {
        // 1M-context requests are standard-priced on Claude 4.6 and later.
        let suffixed = CostEstimator.estimateCost(model: "claude-opus-5[1m]", usage: all1M, billing: postPromo)
        let base = CostEstimator.estimateCost(model: "claude-opus-5", usage: all1M, billing: postPromo)
        XCTAssertEqual(suffixed, base, accuracy: 0.001)
    }

    func testCostEstimatorSyntheticModelIsFree() {
        // Claude Code logs `<synthetic>` for messages it generated locally.
        XCTAssertEqual(CostEstimator.estimateCost(model: "<synthetic>", usage: all1M, billing: postPromo), 0.0)
    }

    func testCostEstimatorUnknownModelUsesSonnetPricing() {
        let usage = TokenUsage(input: 1_000_000)
        let unknownCost = CostEstimator.estimateCost(model: "claude-4-ultra", usage: usage, billing: postPromo)
        let sonnetCost = CostEstimator.estimateCost(model: "claude-sonnet-4-6", usage: usage, billing: postPromo)
        XCTAssertEqual(unknownCost, sonnetCost, accuracy: 0.001)
    }

    func testCostEstimatorUnknownOpusUsesOpusTier() {
        let usage = TokenUsage(input: 1_000_000)
        let cost = CostEstimator.estimateCost(model: "claude-opus-9-9", usage: usage, billing: postPromo)
        XCTAssertEqual(cost, 5.0, accuracy: 0.01)
    }

    func testCostEstimatorCaseInsensitive() {
        let usage = TokenUsage(input: 1_000_000)
        let cost = CostEstimator.estimateCost(model: "CLAUDE-OPUS-4-8", usage: usage, billing: postPromo)
        XCTAssertEqual(cost, 5.0, accuracy: 0.01)
    }

    func testCostEstimatorZeroUsageReturnsZero() {
        let cost = CostEstimator.estimateCost(model: "claude-opus-4-8", usage: TokenUsage(), billing: postPromo)
        XCTAssertEqual(cost, 0.0)
    }

    // MARK: - Model ID normalisation
    //
    // Prefix matching is anchored, so anything wrapping the ID has to be
    // stripped first or the lookup misses the table and silently guesses.

    func testProviderPrefixedIDsResolveToPublishedRate() {
        // Bedrock and Vertex prefix the provider onto the model ID. Opus 4.1
        // bills at $15/$75; a family guess would return the current $5/$25.
        let usage = TokenUsage(input: 1_000_000)
        for model in [
            "anthropic.claude-opus-4-1-20250805",
            "us.anthropic.claude-opus-4-1-20250805",
            "eu.anthropic.claude-opus-4-1",
        ] {
            XCTAssertEqual(
                CostEstimator.estimateCost(model: model, usage: usage, billing: postPromo),
                15.0, accuracy: 0.01, model
            )
            XCTAssertTrue(CostEstimator.hasPublishedRate(for: model), model)
        }
    }

    func testProviderPrefixedIDStillGetsFastModePremium() {
        // The guess path returns before the fast-mode check, so a prefixed ID
        // used to lose the premium entirely.
        let cost = CostEstimator.estimateCost(
            model: "anthropic.claude-opus-5",
            usage: inOut1M,
            billing: billing(speed: "fast")
        )
        XCTAssertEqual(cost, 60.0, accuracy: 0.01)
    }

    func testProviderPrefixedIDStillGetsSonnet5Promo() {
        let cost = CostEstimator.estimateCost(
            model: "anthropic.claude-sonnet-5", usage: inOut1M, billing: billing()
        )
        XCTAssertEqual(cost, 12.0, accuracy: 0.01)
    }

    func testLegacyGenerationFirstHaikuIDResolves() {
        // Real Haiku 3.5 IDs put the generation first: claude-3-5-haiku-*.
        // The family-first spelling never matched them.
        let usage = TokenUsage(input: 1_000_000)
        XCTAssertEqual(
            CostEstimator.estimateCost(model: "claude-3-5-haiku-20241022", usage: usage, billing: postPromo),
            0.80, accuracy: 0.01
        )
        XCTAssertTrue(CostEstimator.hasPublishedRate(for: "claude-3-5-haiku-20241022"))
    }

    func testNormalizationStripsPrefixAndLongContextSuffix() {
        XCTAssertEqual(CostEstimator.normalizedModelID("anthropic.claude-opus-5"), "claude-opus-5")
        XCTAssertEqual(CostEstimator.normalizedModelID("claude-opus-5[1m]"), "claude-opus-5")
        XCTAssertEqual(CostEstimator.normalizedModelID("us.anthropic.claude-opus-5[1m]"), "claude-opus-5")
        XCTAssertEqual(CostEstimator.normalizedModelID("CLAUDE-OPUS-5"), "claude-opus-5")
    }

    func testRetiredModelIsReportedAsGuessed() {
        // Opus 3's published rate is gone, so the family guess ($5/$25) is used
        // and is known to be wrong ($15/$75). It must not read as authoritative.
        XCTAssertFalse(CostEstimator.hasPublishedRate(for: "claude-3-opus-20240229"))
        XCTAssertTrue(CostEstimator.hasPublishedRate(for: "claude-opus-4-8"))
    }

    func testSyntheticIsNotFlaggedAsGuessed() {
        // Free rather than guessed — it was never a billed API call.
        XCTAssertTrue(CostEstimator.hasPublishedRate(for: "<synthetic>"))
    }

    // MARK: - Sonnet 5 introductory pricing
    //
    // Sonnet 5 bills $2/$10 through 2026-08-31, then $3/$15. Cost therefore
    // depends on each message's own timestamp, not on today's date.

    private let inOut1M = TokenUsage(input: 1_000_000, output: 1_000_000)

    func testSonnet5PromoRateDuringWindow() {
        let cost = CostEstimator.estimateCost(model: "claude-sonnet-5", usage: inOut1M, billing: billing())
        XCTAssertEqual(cost, 12.0, accuracy: 0.01)
    }

    func testSonnet5StandardRateAfterWindow() {
        let cost = CostEstimator.estimateCost(model: "claude-sonnet-5", usage: inOut1M, billing: postPromo)
        XCTAssertEqual(cost, 18.0, accuracy: 0.01)
    }

    func testSonnet5PromoBoundary() {
        let last = billing(when: "2026-08-31T23:59:59Z")
        let first = billing(when: "2026-09-01T00:00:00Z")
        XCTAssertEqual(CostEstimator.estimateCost(model: "claude-sonnet-5", usage: inOut1M, billing: last), 12.0, accuracy: 0.01)
        XCTAssertEqual(CostEstimator.estimateCost(model: "claude-sonnet-5", usage: inOut1M, billing: first), 18.0, accuracy: 0.01)
    }

    func testSonnet5PromoCacheRatesScaleWithPromoInputRate() {
        // $2 input → read $0.20, 5-min write $2.50, 1-hour write $4.
        let usage = TokenUsage(cacheRead: 1_000_000, cacheWrite: 1_000_000, cacheWrite1h: 500_000)
        let cost = CostEstimator.estimateCost(model: "claude-sonnet-5", usage: usage, billing: billing())
        XCTAssertEqual(cost, 0.20 + 0.5 * 2.50 + 0.5 * 4.0, accuracy: 0.01)
    }

    func testSonnet5PromoDoesNotAffectOtherModels() {
        let during = CostEstimator.estimateCost(model: "claude-sonnet-4-6", usage: inOut1M, billing: billing())
        let after = CostEstimator.estimateCost(model: "claude-sonnet-4-6", usage: inOut1M, billing: postPromo)
        XCTAssertEqual(during, after, accuracy: 0.001)
        XCTAssertEqual(during, 18.0, accuracy: 0.01)
    }

    // MARK: - Fast mode, data residency, web search

    func testFastModePremiumOnSupportedModels() {
        for model in ["claude-opus-5", "claude-opus-4-8"] {
            let standard = CostEstimator.estimateCost(model: model, usage: inOut1M, billing: billing(speed: "standard"))
            let fast = CostEstimator.estimateCost(model: model, usage: inOut1M, billing: billing(speed: "fast"))
            XCTAssertEqual(standard, 30.0, accuracy: 0.01, model)  // $5 + $25
            XCTAssertEqual(fast, 60.0, accuracy: 0.01, model)      // $10 + $50
        }
    }

    func testFastModeIgnoredOnUnsupportedModels() {
        // Fast mode is not offered on Opus 4.7 or Sonnet, so a stray "fast"
        // must not inflate their cost.
        for model in ["claude-opus-4-7", "claude-sonnet-4-6"] {
            let fast = CostEstimator.estimateCost(model: model, usage: inOut1M, billing: billing(speed: "fast"))
            let standard = CostEstimator.estimateCost(model: model, usage: inOut1M, billing: billing(speed: "standard"))
            XCTAssertEqual(fast, standard, accuracy: 0.001, model)
        }
    }

    func testMissingSpeedIsStandard() {
        let cost = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(speed: nil))
        XCTAssertEqual(cost, 30.0, accuracy: 0.01)
    }

    func testUSDataResidencyMultiplier() {
        let base = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing())
        let us = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(geo: "us"))
        XCTAssertEqual(us, base * 1.1, accuracy: 0.001)
    }

    func testNonUSGeoIsStandardPriced() {
        let base = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing())
        for geo in ["global", "not_available"] {
            let cost = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(geo: geo))
            XCTAssertEqual(cost, base, accuracy: 0.001, geo)
        }
        let none = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(geo: nil))
        XCTAssertEqual(none, base, accuracy: 0.001)
    }

    func testWebSearchBilledPerSearch() {
        // $10 per 1,000 searches.
        let base = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing())
        let withSearches = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(searches: 25))
        XCTAssertEqual(withSearches - base, 0.25, accuracy: 0.0001)
    }

    func testSearchChargesNotScaledByDataResidency() {
        // The 1.1x multiplier applies to token categories, not per-search fees.
        let tokensOnly = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(geo: "us"))
        let withSearch = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(geo: "us", searches: 10))
        XCTAssertEqual(withSearch - tokensOnly, 0.10, accuracy: 0.0001)
    }

    func testFastModeAndResidencyStack() {
        let cost = CostEstimator.estimateCost(model: "claude-opus-5", usage: inOut1M, billing: billing(speed: "fast", geo: "us"))
        XCTAssertEqual(cost, 60.0 * 1.1, accuracy: 0.01)
    }

    // MARK: - TokenFormatter

    func testTokenFormatterZero() {
        XCTAssertEqual(TokenFormatter.format(0), "0")
    }

    func testTokenFormatterHundreds() {
        XCTAssertEqual(TokenFormatter.format(999), "999")
    }

    func testTokenFormatterThousands() {
        XCTAssertEqual(TokenFormatter.format(1000), "1.0K")
        XCTAssertEqual(TokenFormatter.format(12345), "12.3K")
        XCTAssertEqual(TokenFormatter.format(999_999), "1000.0K")
    }

    func testTokenFormatterMillions() {
        XCTAssertEqual(TokenFormatter.format(1_000_000), "1.0M")
        XCTAssertEqual(TokenFormatter.format(151_700_000), "151.7M")
    }

    func testTokenFormatterBillions() {
        XCTAssertEqual(TokenFormatter.format(1_000_000_000), "1.0B")
        XCTAssertEqual(TokenFormatter.format(2_800_000_000), "2.8B")
    }

    func testTokenFormatterCostSmall() {
        XCTAssertEqual(TokenFormatter.formatCost(0.0), "$0.00")
        XCTAssertEqual(TokenFormatter.formatCost(1.50), "$1.50")
        XCTAssertEqual(TokenFormatter.formatCost(99.99), "$99.99")
    }

    func testTokenFormatterCostMedium() {
        XCTAssertEqual(TokenFormatter.formatCost(100.0), "$100.0")
        XCTAssertEqual(TokenFormatter.formatCost(999.9), "$999.9")
    }

    func testTokenFormatterCostLarge() {
        XCTAssertEqual(TokenFormatter.formatCost(1000.0), "$1000")
        XCTAssertEqual(TokenFormatter.formatCost(2100.5), "$2101")
    }

    // MARK: - AggregatedStats

    func testAggregatedStatsSessionCountFromSet() {
        var stats = AggregatedStats()
        stats.sessionIds = ["a", "b", "c"]
        XCTAssertEqual(stats.sessionCount, 3)
    }

    func testAggregatedStatsDefaultsAreZero() {
        let stats = AggregatedStats()
        XCTAssertEqual(stats.totalUsage.total, 0)
        XCTAssertEqual(stats.totalMessages, 0)
        XCTAssertEqual(stats.sessionCount, 0)
        XCTAssertEqual(stats.estimatedCost, 0.0)
        XCTAssertTrue(stats.modelBreakdown.isEmpty)
        XCTAssertTrue(stats.dailyBreakdown.isEmpty)
    }

    // MARK: - ModelStats

    func testModelStatsIdIsModelName() {
        let ms = ModelStats(model: "claude-opus-4-6", messageCount: 5, usage: TokenUsage())
        XCTAssertEqual(ms.id, "claude-opus-4-6")
    }
}
