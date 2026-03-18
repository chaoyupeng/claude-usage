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

    // MARK: - CostEstimator

    func testCostEstimatorOpusPricing() {
        let usage = TokenUsage(input: 1_000_000, output: 1_000_000, cacheRead: 1_000_000, cacheWrite: 1_000_000)
        let cost = CostEstimator.estimateCost(model: "claude-opus-4-6", usage: usage)
        // input: $15, output: $75, cacheRead: $1.50, cacheWrite: $18.75
        XCTAssertEqual(cost, 110.25, accuracy: 0.01)
    }

    func testCostEstimatorSonnetPricing() {
        let usage = TokenUsage(input: 1_000_000, output: 1_000_000, cacheRead: 1_000_000, cacheWrite: 1_000_000)
        let cost = CostEstimator.estimateCost(model: "claude-sonnet-4-6", usage: usage)
        // input: $3, output: $15, cacheRead: $0.30, cacheWrite: $3.75
        XCTAssertEqual(cost, 22.05, accuracy: 0.01)
    }

    func testCostEstimatorHaikuPricing() {
        let usage = TokenUsage(input: 1_000_000, output: 1_000_000, cacheRead: 1_000_000, cacheWrite: 1_000_000)
        let cost = CostEstimator.estimateCost(model: "claude-haiku-4-5", usage: usage)
        // input: $0.25, output: $1.25, cacheRead: $0.025, cacheWrite: $0.30
        XCTAssertEqual(cost, 1.825, accuracy: 0.001)
    }

    func testCostEstimatorUnknownModelUsesSonnetPricing() {
        let usage = TokenUsage(input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0)
        let unknownCost = CostEstimator.estimateCost(model: "claude-4-ultra", usage: usage)
        let sonnetCost = CostEstimator.estimateCost(model: "claude-sonnet-4-6", usage: usage)
        XCTAssertEqual(unknownCost, sonnetCost)
    }

    func testCostEstimatorCaseInsensitive() {
        let usage = TokenUsage(input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0)
        let cost = CostEstimator.estimateCost(model: "Claude-3-OPUS-20240229", usage: usage)
        XCTAssertEqual(cost, 15.0, accuracy: 0.01)
    }

    func testCostEstimatorZeroUsageReturnsZero() {
        let cost = CostEstimator.estimateCost(model: "claude-opus-4-6", usage: TokenUsage())
        XCTAssertEqual(cost, 0.0)
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
