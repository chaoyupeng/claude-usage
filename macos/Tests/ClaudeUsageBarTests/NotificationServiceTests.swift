import XCTest
@testable import ClaudeUsageBar

final class NotificationServiceTests: XCTestCase {
    func testNoAlertsWhenAllOff() {
        let alerts = crossedThresholds(
            threshold5h: 0, threshold7d: 0, thresholdExtra: 0,
            previous5h: 40, previous7d: 30, previousExtra: 20,
            current5h: 90, current7d: 85, currentExtra: 80
        )
        XCTAssertTrue(alerts.isEmpty)
    }

    func testOnly5hFires() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 70, previous7d: 50, previousExtra: 10,
            current5h: 85, current7d: 90, currentExtra: 50
        )
        XCTAssertEqual(alerts, [ThresholdAlert(window: "5-hour", pct: 85)])
    }

    func testOnly7dFires() {
        let alerts = crossedThresholds(
            threshold5h: 0, threshold7d: 80, thresholdExtra: 0,
            previous5h: 70, previous7d: 70, previousExtra: 10,
            current5h: 85, current7d: 85, currentExtra: 50
        )
        XCTAssertEqual(alerts, [ThresholdAlert(window: "7-day", pct: 85)])
    }

    func testOnlyExtraFires() {
        let alerts = crossedThresholds(
            threshold5h: 0, threshold7d: 0, thresholdExtra: 50,
            previous5h: 70, previous7d: 70, previousExtra: 40,
            current5h: 85, current7d: 85, currentExtra: 60
        )
        XCTAssertEqual(alerts, [ThresholdAlert(window: "Extra usage", pct: 60)])
    }

    func testAllThreeFireSimultaneously() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 80, thresholdExtra: 50,
            previous5h: 70, previous7d: 70, previousExtra: 40,
            current5h: 85, current7d: 90, currentExtra: 60
        )
        XCTAssertEqual(alerts, [
            ThresholdAlert(window: "5-hour", pct: 85),
            ThresholdAlert(window: "7-day", pct: 90),
            ThresholdAlert(window: "Extra usage", pct: 60),
        ])
    }

    func testNoAlertWhenStayingAbove() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 80, thresholdExtra: 50,
            previous5h: 85, previous7d: 90, previousExtra: 60,
            current5h: 88, current7d: 92, currentExtra: 65
        )
        XCTAssertTrue(alerts.isEmpty)
    }

    func testNoAlertWhenStayingBelow() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 80, thresholdExtra: 50,
            previous5h: 50, previous7d: 60, previousExtra: 30,
            current5h: 70, current7d: 75, currentExtra: 45
        )
        XCTAssertTrue(alerts.isEmpty)
    }

    func testExactThresholdTriggers() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 79, previous7d: 50, previousExtra: 10,
            current5h: 80, current7d: 50, currentExtra: 10
        )
        XCTAssertEqual(alerts, [ThresholdAlert(window: "5-hour", pct: 80)])
    }

    func testFirstPollFiresWhenAlreadyAboveThreshold() {
        let alerts = crossedThresholds(
            threshold5h: 25, threshold7d: 5, thresholdExtra: 0,
            previous5h: 0, previous7d: 0, previousExtra: 0,
            current5h: 60, current7d: 40, currentExtra: 10
        )
        XCTAssertEqual(alerts, [
            ThresholdAlert(window: "5-hour", pct: 60),
            ThresholdAlert(window: "7-day", pct: 40),
        ])
    }

    func testFirstPollDoesNotFireWhenBelowThreshold() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 80, thresholdExtra: 0,
            previous5h: 0, previous7d: 0, previousExtra: 0,
            current5h: 30, current7d: 50, currentExtra: 10
        )
        XCTAssertTrue(alerts.isEmpty)
    }

    func testDifferentThresholdsPerWindow() {
        let alerts = crossedThresholds(
            threshold5h: 90, threshold7d: 50, thresholdExtra: 70,
            previous5h: 85, previous7d: 45, previousExtra: 65,
            current5h: 95, current7d: 55, currentExtra: 75
        )
        XCTAssertEqual(alerts, [
            ThresholdAlert(window: "5-hour", pct: 95),
            ThresholdAlert(window: "7-day", pct: 55),
            ThresholdAlert(window: "Extra usage", pct: 75),
        ])
    }

    // MARK: - New edge cases

    func testReCrossingAfterDropBelowFiresAgain() {
        // Drop below, then cross again — should fire on second crossing
        let firstCross = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 70, previous7d: 0, previousExtra: 0,
            current5h: 85, current7d: 0, currentExtra: 0
        )
        XCTAssertEqual(firstCross.count, 1)

        // Stays above — no alert
        let staysAbove = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 85, previous7d: 0, previousExtra: 0,
            current5h: 90, current7d: 0, currentExtra: 0
        )
        XCTAssertTrue(staysAbove.isEmpty)

        // Drops below
        let dropsBelow = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 90, previous7d: 0, previousExtra: 0,
            current5h: 70, current7d: 0, currentExtra: 0
        )
        XCTAssertTrue(dropsBelow.isEmpty)

        // Re-crosses — should fire again
        let reCross = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 70, previous7d: 0, previousExtra: 0,
            current5h: 82, current7d: 0, currentExtra: 0
        )
        XCTAssertEqual(reCross.count, 1)
    }

    func testMaxThreshold100FiresAt100() {
        let alerts = crossedThresholds(
            threshold5h: 100, threshold7d: 0, thresholdExtra: 0,
            previous5h: 99, previous7d: 0, previousExtra: 0,
            current5h: 100, current7d: 0, currentExtra: 0
        )
        XCTAssertEqual(alerts, [ThresholdAlert(window: "5-hour", pct: 100)])
    }

    func testBoundaryRoundingInPct() {
        let alerts = crossedThresholds(
            threshold5h: 80, threshold7d: 0, thresholdExtra: 0,
            previous5h: 79.4, previous7d: 0, previousExtra: 0,
            current5h: 80.6, current7d: 0, currentExtra: 0
        )
        XCTAssertEqual(alerts.first?.pct, 81) // round(80.6) = 81
    }
}
