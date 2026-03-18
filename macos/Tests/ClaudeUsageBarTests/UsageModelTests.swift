import XCTest
@testable import ClaudeUsageBar

final class UsageModelTests: XCTestCase {
    func testResetDateParsesTimestampWithoutTimezoneAsUTC() throws {
        let bucket = UsageBucket(
            utilization: 25.0,
            resetsAt: "2026-03-05T18:00:00"
        )

        XCTAssertEqual(bucket.resetsAtDate, date("2026-03-05T18:00:00Z"))
    }

    func testReconcileKeepsPreviousResetWhenServerTemporarilyDropsIt() throws {
        let previousReset = date("2026-03-05T18:00:00Z")
        let previous = usageResponse(
            fiveHour: UsageBucket(utilization: 88.0, resetsAt: iso(previousReset))
        )
        let current = usageResponse(
            fiveHour: UsageBucket(utilization: 89.0, resetsAt: nil)
        )

        let reconciled = current.reconciled(
            with: previous,
            now: date("2026-03-05T17:30:00Z")
        )

        XCTAssertEqual(reconciled.fiveHour?.resetsAtDate, previousReset)
    }

    func testReconcileAdvancesResetAfterRolloverWhenServerDropsIt() throws {
        let previousReset = date("2026-03-05T18:00:00Z")
        let previous = usageResponse(
            fiveHour: UsageBucket(utilization: 100.0, resetsAt: iso(previousReset))
        )
        let current = usageResponse(
            fiveHour: UsageBucket(utilization: 2.0, resetsAt: "not-a-date")
        )

        let reconciled = current.reconciled(
            with: previous,
            now: date("2026-03-05T18:05:00Z")
        )

        XCTAssertEqual(reconciled.fiveHour?.resetsAtDate, date("2026-03-05T23:00:00Z"))
    }

    func testReconcilePreservesValidServerReset() throws {
        let previous = usageResponse(
            fiveHour: UsageBucket(utilization: 100.0, resetsAt: "2026-03-05T18:00:00Z")
        )
        let current = usageResponse(
            fiveHour: UsageBucket(utilization: 2.0, resetsAt: "2026-03-05T22:00:00Z")
        )

        let reconciled = current.reconciled(
            with: previous,
            now: date("2026-03-05T18:05:00Z")
        )

        XCTAssertEqual(reconciled.fiveHour?.resetsAtDate, date("2026-03-05T22:00:00Z"))
    }

    // MARK: - resetsAtDate edge cases

    func testResetDateNilResetsAt() {
        let bucket = UsageBucket(utilization: 25.0, resetsAt: nil)
        XCTAssertNil(bucket.resetsAtDate)
    }

    func testResetDateEmptyString() {
        let bucket = UsageBucket(utilization: 25.0, resetsAt: "")
        XCTAssertNil(bucket.resetsAtDate)
    }

    func testResetDateMicrosecondPrecision() {
        let bucket = UsageBucket(utilization: 25.0, resetsAt: "2026-03-05T18:00:00.123456")
        XCTAssertNotNil(bucket.resetsAtDate)
    }

    func testResetDateMillisecondPrecision() {
        let bucket = UsageBucket(utilization: 25.0, resetsAt: "2026-03-05T18:00:00.123")
        XCTAssertNotNil(bucket.resetsAtDate)
    }

    func testResetDateISO8601WithFractionalSeconds() {
        let bucket = UsageBucket(utilization: 25.0, resetsAt: "2026-03-05T18:00:00.500Z")
        XCTAssertNotNil(bucket.resetsAtDate)
    }

    // MARK: - reconciled edge cases

    func testReconciledWithNoPreviousReturnsSelf() {
        let current = usageResponse(
            fiveHour: UsageBucket(utilization: 50.0, resetsAt: nil)
        )
        let reconciled = current.reconciled(with: nil, now: Date())
        XCTAssertNil(reconciled.fiveHour?.resetsAtDate)
    }

    func testReconciledSevenDayBucket() {
        let previousReset = date("2026-03-01T00:00:00Z")
        let previous = UsageResponse(
            fiveHour: nil,
            sevenDay: UsageBucket(utilization: 50.0, resetsAt: iso(previousReset)),
            sevenDayOpus: nil,
            sevenDaySonnet: nil,
            extraUsage: nil
        )
        let current = UsageResponse(
            fiveHour: nil,
            sevenDay: UsageBucket(utilization: 10.0, resetsAt: nil),
            sevenDayOpus: nil,
            sevenDaySonnet: nil,
            extraUsage: nil
        )
        let reconciled = current.reconciled(
            with: previous,
            now: date("2026-03-08T01:00:00Z")
        )
        XCTAssertNotNil(reconciled.sevenDay?.resetsAtDate)
    }

    // MARK: - ExtraUsage

    func testExtraUsageCreditConversion() {
        let extra = ExtraUsage(isEnabled: true, utilization: 50.0, usedCredits: 5230, monthlyLimit: 28000)
        XCTAssertEqual(extra.usedCreditsAmount, 52.30)
        XCTAssertEqual(extra.monthlyLimitAmount, 280.00)
    }

    func testExtraUsageNilCredits() {
        let extra = ExtraUsage(isEnabled: true, utilization: nil, usedCredits: nil, monthlyLimit: nil)
        XCTAssertNil(extra.usedCreditsAmount)
        XCTAssertNil(extra.monthlyLimitAmount)
    }

    func testExtraUsageFormatUSD() {
        XCTAssertEqual(ExtraUsage.formatUSD(0), "$0.00")
        XCTAssertEqual(ExtraUsage.formatUSD(52.30), "$52.30")
        XCTAssertEqual(ExtraUsage.formatUSD(100.00), "$100.00")
    }

    // MARK: - UsageResponse JSON decoding

    func testUsageResponseDecoding() throws {
        let json = """
        {
            "five_hour": {"utilization": 42.5, "resets_at": "2026-03-05T18:00:00Z"},
            "seven_day": {"utilization": 15.0}
        }
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(UsageResponse.self, from: json)
        XCTAssertEqual(decoded.fiveHour?.utilization, 42.5)
        XCTAssertEqual(decoded.sevenDay?.utilization, 15.0)
        XCTAssertNil(decoded.sevenDayOpus)
        XCTAssertNil(decoded.extraUsage)
    }

    // MARK: - Helpers

    private func usageResponse(fiveHour: UsageBucket? = nil) -> UsageResponse {
        UsageResponse(
            fiveHour: fiveHour,
            sevenDay: nil,
            sevenDayOpus: nil,
            sevenDaySonnet: nil,
            extraUsage: nil
        )
    }

    private func date(_ value: String) -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) {
            return date
        }

        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)!
    }

    private func iso(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }
}
