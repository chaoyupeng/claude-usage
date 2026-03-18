import XCTest
@testable import ClaudeUsageBar

final class ClaudeLogParserTests: XCTestCase {

    // MARK: - parseJSONLData

    func testParseEmptyData() {
        let records = ClaudeLogParser.parseJSONLData(Data())
        XCTAssertTrue(records.isEmpty)
    }

    func testParseNonAssistantMessagesSkipped() {
        let jsonl = """
        {"type":"user","message":{},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        {"type":"system","message":{},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseSingleValidAssistantMessage() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":200,"cache_creation_input_tokens":300}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"session-1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].model, "claude-sonnet-4-6")
        XCTAssertEqual(records[0].sessionId, "session-1")
        XCTAssertEqual(records[0].usage.input, 100)
        XCTAssertEqual(records[0].usage.output, 50)
        XCTAssertEqual(records[0].usage.cacheRead, 200)
        XCTAssertEqual(records[0].usage.cacheWrite, 300)
        XCTAssertEqual(records[0].usage.total, 650)
    }

    func testParseCorruptLineSkippedOthersKept() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        not valid json at all!!!
        {"type":"assistant","message":{"model":"claude-opus-4-6","usage":{"input_tokens":30,"output_tokens":40}},"timestamp":"2026-03-18T11:00:00.000Z","sessionId":"s2"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertEqual(records.count, 2)
        XCTAssertEqual(records[0].model, "claude-sonnet-4-6")
        XCTAssertEqual(records[1].model, "claude-opus-4-6")
    }

    func testParseMissingMessageKeySkipped() {
        let jsonl = """
        {"type":"assistant","timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseMissingModelSkipped() {
        let jsonl = """
        {"type":"assistant","message":{"usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseMissingUsageSkipped() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6"},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseZeroTokensSkipped() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":0,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseMissingOptionalTokenFieldsDefaultToZero() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].usage.cacheRead, 0)
        XCTAssertEqual(records[0].usage.cacheWrite, 0)
        XCTAssertEqual(records[0].usage.total, 30)
    }

    func testParseInvalidTimestampSkipped() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"not-a-date","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testParseMissingSessionIdDefaultsToEmpty() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"2026-03-18T10:00:00.000Z"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].sessionId, "")
    }

    // MARK: - parseDate

    func testParseDateWithFractionalSeconds() {
        let date = ClaudeLogParser.parseDate("2026-03-18T09:17:53.834Z")
        XCTAssertNotNil(date)
    }

    func testParseDateWithoutFractionalSeconds() {
        let date = ClaudeLogParser.parseDate("2026-03-18T09:17:53Z")
        XCTAssertNotNil(date)
    }

    func testParseDateInvalidReturnsNil() {
        XCTAssertNil(ClaudeLogParser.parseDate("not-a-date"))
        XCTAssertNil(ClaudeLogParser.parseDate(""))
    }

    // MARK: - aggregate

    func testAggregateEmptyRecords() {
        let stats = ClaudeLogParser.aggregate([])
        XCTAssertEqual(stats.totalMessages, 0)
        XCTAssertEqual(stats.totalUsage.total, 0)
        XCTAssertEqual(stats.sessionCount, 0)
        XCTAssertEqual(stats.estimatedCost, 0.0)
        XCTAssertEqual(stats.dailyBreakdown.count, 14)
        XCTAssertEqual(stats.lastHourMinutes.count, 60)
    }

    func testAggregateSingleRecord() {
        let now = Date()
        let record = MessageRecord(
            timestamp: now,
            model: "claude-sonnet-4-6",
            sessionId: "s1",
            usage: TokenUsage(input: 100, output: 200, cacheRead: 0, cacheWrite: 0)
        )
        let stats = ClaudeLogParser.aggregate([record], now: now)
        XCTAssertEqual(stats.totalMessages, 1)
        XCTAssertEqual(stats.sessionCount, 1)
        XCTAssertEqual(stats.totalUsage.total, 300)
        XCTAssertEqual(stats.modelBreakdown.count, 1)
        XCTAssertEqual(stats.modelBreakdown[0].model, "claude-sonnet-4-6")
    }

    func testAggregateMultipleModels() {
        let now = Date()
        let records = [
            MessageRecord(timestamp: now, model: "claude-opus-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 100, output: 500, cacheRead: 0, cacheWrite: 0)),
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 50, output: 100, cacheRead: 0, cacheWrite: 0)),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        XCTAssertEqual(stats.modelBreakdown.count, 2)
        // Sorted by total tokens descending — opus first
        XCTAssertEqual(stats.modelBreakdown[0].model, "claude-opus-4-6")
        XCTAssertEqual(stats.modelBreakdown[1].model, "claude-sonnet-4-6")
    }

    func testAggregateSameModelAccumulates() {
        let now = Date()
        let records = [
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 10, output: 20, cacheRead: 0, cacheWrite: 0)),
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 30, output: 40, cacheRead: 0, cacheWrite: 0)),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        XCTAssertEqual(stats.modelBreakdown.count, 1)
        XCTAssertEqual(stats.modelBreakdown[0].messageCount, 2)
        XCTAssertEqual(stats.modelBreakdown[0].usage.total, 100)
    }

    func testAggregateTodayVsOlderRecords() {
        let now = Date()
        let yesterday = now.addingTimeInterval(-86400 * 2)
        let records = [
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 100, output: 0, cacheRead: 0, cacheWrite: 0)),
            MessageRecord(timestamp: yesterday, model: "claude-sonnet-4-6", sessionId: "s2",
                          usage: TokenUsage(input: 500, output: 0, cacheRead: 0, cacheWrite: 0)),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        XCTAssertEqual(stats.todayMessages, 1)
        XCTAssertEqual(stats.todayUsage.input, 100)
        XCTAssertEqual(stats.totalMessages, 2)
    }

    func testAggregateMultipleSessions() {
        let now = Date()
        let records = [
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 10, output: 10, cacheRead: 0, cacheWrite: 0)),
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s2",
                          usage: TokenUsage(input: 10, output: 10, cacheRead: 0, cacheWrite: 0)),
            MessageRecord(timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                          usage: TokenUsage(input: 10, output: 10, cacheRead: 0, cacheWrite: 0)),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        XCTAssertEqual(stats.sessionCount, 2)
    }

    func testAggregateDailyBreakdownAlways14Days() {
        let now = Date()
        let stats = ClaudeLogParser.aggregate([], now: now)
        XCTAssertEqual(stats.dailyBreakdown.count, 14)
        // All zero-filled
        for day in stats.dailyBreakdown {
            XCTAssertEqual(day.messageCount, 0)
            XCTAssertEqual(day.usage.total, 0)
        }
    }

    func testAggregateLastHourMinutesAlways60() {
        let now = Date()
        let stats = ClaudeLogParser.aggregate([], now: now)
        XCTAssertEqual(stats.lastHourMinutes.count, 60)
    }

    func testAggregateLastHourBucketing() {
        let now = Date()
        let calendar = Calendar.current
        let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: now)
        let currentMinute = calendar.date(from: comps)!
        let fiveMinAgo = currentMinute.addingTimeInterval(-300)

        let record = MessageRecord(
            timestamp: fiveMinAgo.addingTimeInterval(10), // within 5-min-ago minute
            model: "claude-sonnet-4-6",
            sessionId: "s1",
            usage: TokenUsage(input: 100, output: 0, cacheRead: 0, cacheWrite: 0)
        )
        let stats = ClaudeLogParser.aggregate([record], now: now)
        let nonZero = stats.lastHourMinutes.filter { $0.tokens > 0 }
        XCTAssertEqual(nonZero.count, 1)
        XCTAssertEqual(nonZero[0].tokens, 100)
    }

    func testAggregateCostEstimation() {
        let now = Date()
        let record = MessageRecord(
            timestamp: now,
            model: "claude-opus-4-6",
            sessionId: "s1",
            usage: TokenUsage(input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0)
        )
        let stats = ClaudeLogParser.aggregate([record], now: now)
        XCTAssertEqual(stats.estimatedCost, 15.0, accuracy: 0.01)
    }

    // MARK: - Additional edge cases

    func testParseTrailingNewlinesIgnored() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"2026-03-18T10:00:00.000Z","sessionId":"s1"}

        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertEqual(records.count, 1)
    }

    func testParseEmptyTimestampSkipped() {
        let jsonl = """
        {"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":20}},"timestamp":"","sessionId":"s1"}
        """
        let records = ClaudeLogParser.parseJSONLData(Data(jsonl.utf8))
        XCTAssertTrue(records.isEmpty)
    }

    func testAggregateYesterdayOnlyRecords() {
        let now = Date()
        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: now)!
        let record = MessageRecord(
            timestamp: yesterday,
            model: "claude-sonnet-4-6",
            sessionId: "s1",
            usage: TokenUsage(input: 100, output: 200, cacheRead: 0, cacheWrite: 0)
        )
        let stats = ClaudeLogParser.aggregate([record], now: now)
        XCTAssertEqual(stats.totalMessages, 1)
        XCTAssertEqual(stats.todayMessages, 0)
        XCTAssertEqual(stats.todayUsage.total, 0)
    }

    func testAggregateSameMinuteAccumulation() {
        let now = Date()
        let calendar = Calendar.current
        let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: now)
        let currentMinute = calendar.date(from: comps)!

        let records = [
            MessageRecord(
                timestamp: currentMinute.addingTimeInterval(5),
                model: "claude-sonnet-4-6", sessionId: "s1",
                usage: TokenUsage(input: 100, output: 0, cacheRead: 0, cacheWrite: 0)
            ),
            MessageRecord(
                timestamp: currentMinute.addingTimeInterval(10),
                model: "claude-sonnet-4-6", sessionId: "s1",
                usage: TokenUsage(input: 200, output: 0, cacheRead: 0, cacheWrite: 0)
            ),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        let nonZero = stats.lastHourMinutes.filter { $0.tokens > 0 }
        XCTAssertEqual(nonZero.count, 1)
        XCTAssertEqual(nonZero[0].tokens, 300)
    }

    func testAggregateMultiModelCost() {
        let now = Date()
        let records = [
            MessageRecord(
                timestamp: now, model: "claude-opus-4-6", sessionId: "s1",
                usage: TokenUsage(input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0)
            ),
            MessageRecord(
                timestamp: now, model: "claude-sonnet-4-6", sessionId: "s1",
                usage: TokenUsage(input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0)
            ),
        ]
        let stats = ClaudeLogParser.aggregate(records, now: now)
        // opus input: $15, sonnet input: $3 → total $18
        XCTAssertEqual(stats.estimatedCost, 18.0, accuracy: 0.01)
    }
}
