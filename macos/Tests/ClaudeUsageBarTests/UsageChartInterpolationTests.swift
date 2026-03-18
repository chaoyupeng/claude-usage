import XCTest
@testable import ClaudeUsageBar

final class UsageChartInterpolationTests: XCTestCase {
    func testInterpolateValuesClampsNegativeOvershootAfterReset() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.3, pct7d: 0.3),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.7, pct7d: 0.7),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.0, pct7d: 0.0),
            UsageDataPoint(timestamp: base.addingTimeInterval(3), pct5h: 1.0, pct7d: 1.0),
        ]

        XCTAssertLessThan(
            UsageChartInterpolation.catmullRom(0.3, 0.7, 0.0, 1.0, t: 0.966),
            0
        )

        let interpolated = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(1.966),
            in: points
        )

        XCTAssertEqual(interpolated?.pct5h, 0)
        XCTAssertEqual(interpolated?.pct7d, 0)
    }

    func testInterpolateValuesClampsPositiveOvershootToHundredPercent() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.0, pct7d: 0.0),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.5, pct7d: 0.5),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 1.0, pct7d: 1.0),
            UsageDataPoint(timestamp: base.addingTimeInterval(3), pct5h: 0.0, pct7d: 0.0),
        ]

        XCTAssertGreaterThan(
            UsageChartInterpolation.catmullRom(0.0, 0.5, 1.0, 0.0, t: 0.911),
            1
        )

        let interpolated = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(1.911),
            in: points
        )

        XCTAssertEqual(interpolated?.pct5h, 1)
        XCTAssertEqual(interpolated?.pct7d, 1)
    }

    // MARK: - Edge cases

    func testInterpolateWithZeroPointsReturnsNil() {
        let result = UsageChartInterpolation.interpolateValues(at: Date(), in: [])
        XCTAssertNil(result)
    }

    func testInterpolateWithOnePointReturnsNil() {
        let point = UsageDataPoint(timestamp: Date(), pct5h: 0.5, pct7d: 0.5)
        let result = UsageChartInterpolation.interpolateValues(at: Date(), in: [point])
        XCTAssertNil(result)
    }

    func testInterpolateWithExactlyTwoPoints() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.2, pct7d: 0.3),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.8, pct7d: 0.9),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(1), in: points
        )
        XCTAssertNotNil(result)
    }

    func testInterpolateDateBeforeFirstPointReturnsZero() {
        let base = Date(timeIntervalSince1970: 100)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.5, pct7d: 0.5),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.8, pct7d: 0.8),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: Date(timeIntervalSince1970: 50), in: points
        )
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.pct5h, 0)
        XCTAssertEqual(result?.pct7d, 0)
    }

    func testInterpolateDateAfterLastPointReturnsZero() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.5, pct7d: 0.5),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.8, pct7d: 0.8),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(10), in: points
        )
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.pct5h, 0)
        XCTAssertEqual(result?.pct7d, 0)
    }

    func testInterpolateExactlyOnPointReturnsPointValues() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.2, pct7d: 0.3),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.5, pct7d: 0.6),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.8, pct7d: 0.9),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(1), in: points
        )
        XCTAssertNotNil(result)
        XCTAssertEqual(result!.pct5h, 0.5, accuracy: 0.01)
        XCTAssertEqual(result!.pct7d, 0.6, accuracy: 0.01)
    }

    func testInterpolateWithUnsortedPointsStillWorks() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.8, pct7d: 0.8),
            UsageDataPoint(timestamp: base, pct5h: 0.2, pct7d: 0.2),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.5, pct7d: 0.5),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(0.5), in: points
        )
        XCTAssertNotNil(result)
    }

    func testCatmullRomAtT0ReturnsP1() {
        let result = UsageChartInterpolation.catmullRom(0.1, 0.4, 0.7, 1.0, t: 0)
        XCTAssertEqual(result, 0.4, accuracy: 0.001)
    }

    func testCatmullRomAtT1ReturnsP2() {
        let result = UsageChartInterpolation.catmullRom(0.1, 0.4, 0.7, 1.0, t: 1)
        XCTAssertEqual(result, 0.7, accuracy: 0.001)
    }

    func testInterpolateSonnetNilWhenPointsLackSonnetData() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.2, pct7d: 0.3),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.5, pct7d: 0.6),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.8, pct7d: 0.9),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(0.5), in: points
        )
        XCTAssertNil(result?.pctSonnet7d)
    }

    func testInterpolateSonnetPresentWhenAllPointsHaveIt() {
        let base = Date(timeIntervalSince1970: 0)
        let points = [
            UsageDataPoint(timestamp: base, pct5h: 0.2, pct7d: 0.3, pctSonnet7d: 0.1),
            UsageDataPoint(timestamp: base.addingTimeInterval(1), pct5h: 0.5, pct7d: 0.6, pctSonnet7d: 0.4),
            UsageDataPoint(timestamp: base.addingTimeInterval(2), pct5h: 0.8, pct7d: 0.9, pctSonnet7d: 0.7),
            UsageDataPoint(timestamp: base.addingTimeInterval(3), pct5h: 0.9, pct7d: 1.0, pctSonnet7d: 0.9),
        ]
        let result = UsageChartInterpolation.interpolateValues(
            at: base.addingTimeInterval(1.5), in: points
        )
        XCTAssertNotNil(result?.pctSonnet7d)
    }
}
