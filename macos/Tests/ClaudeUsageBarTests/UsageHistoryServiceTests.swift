import XCTest
@testable import ClaudeUsageBar

@MainActor
final class UsageHistoryServiceTests: XCTestCase {
    func testRecordDataPointAppendsToHistory() {
        let service = UsageHistoryService()
        service.recordDataPoint(pct5h: 0.5, pct7d: 0.3)

        XCTAssertEqual(service.history.dataPoints.count, 1)
        XCTAssertEqual(service.history.dataPoints[0].pct5h, 0.5)
        XCTAssertEqual(service.history.dataPoints[0].pct7d, 0.3)
        XCTAssertNil(service.history.dataPoints[0].pctSonnet7d)
    }

    func testRecordDataPointWithSonnet() {
        let service = UsageHistoryService()
        service.recordDataPoint(pct5h: 0.5, pct7d: 0.3, pctSonnet7d: 0.2)

        XCTAssertEqual(service.history.dataPoints.count, 1)
        XCTAssertEqual(service.history.dataPoints[0].pctSonnet7d, 0.2)
    }

    func testDownsampleReturnsAllWhenUnderThreshold() {
        let service = UsageHistoryService()
        // Add fewer points than the target for any range
        for i in 0..<10 {
            service.recordDataPoint(
                pct5h: Double(i) / 10.0,
                pct7d: Double(i) / 20.0
            )
        }

        let points = service.downsampledPoints(for: .hour1)
        XCTAssertEqual(points.count, 10)
    }

    func testDownsampleReducesWhenOverThreshold() {
        let service = UsageHistoryService()
        let base = Date()

        // Add more points than any range's target (200+)
        for i in 0..<300 {
            let point = UsageDataPoint(
                timestamp: base.addingTimeInterval(Double(i) * 10),
                pct5h: Double(i) / 300.0,
                pct7d: Double(i) / 600.0
            )
            service.history.dataPoints.append(point)
        }

        let points = service.downsampledPoints(for: .hour1)
        XCTAssertLessThanOrEqual(points.count, TimeRange.hour1.targetPointCount)
    }

    func testDownsampleAveragesSonnetValues() {
        let service = UsageHistoryService()
        let base = Date()

        // Create enough points to trigger downsampling for .hour1
        for i in 0..<200 {
            let point = UsageDataPoint(
                timestamp: base.addingTimeInterval(Double(i) * 10),
                pct5h: 0.5,
                pct7d: 0.5,
                pctSonnet7d: 0.4
            )
            service.history.dataPoints.append(point)
        }

        let points = service.downsampledPoints(for: .hour1)
        let hasSonnet = points.contains { $0.pctSonnet7d != nil }
        XCTAssertTrue(hasSonnet)
    }

    func testDownsampleOmitsSonnetWhenAllNil() {
        let service = UsageHistoryService()
        let base = Date()

        for i in 0..<200 {
            let point = UsageDataPoint(
                timestamp: base.addingTimeInterval(Double(i) * 10),
                pct5h: 0.5,
                pct7d: 0.5,
                pctSonnet7d: nil
            )
            service.history.dataPoints.append(point)
        }

        let points = service.downsampledPoints(for: .hour1)
        let hasSonnet = points.contains { $0.pctSonnet7d != nil }
        XCTAssertFalse(hasSonnet)
    }

    func testFlushAndReloadRoundTrip() throws {
        let service = UsageHistoryService()
        service.recordDataPoint(pct5h: 0.42, pct7d: 0.18, pctSonnet7d: 0.1)
        service.flushToDisk()

        let service2 = UsageHistoryService()
        service2.loadHistory()

        XCTAssertEqual(service2.history.dataPoints.count, 1)
        XCTAssertEqual(service2.history.dataPoints[0].pct5h, 0.42, accuracy: 0.001)
        XCTAssertEqual(service2.history.dataPoints[0].pct7d, 0.18, accuracy: 0.001)
        XCTAssertEqual(service2.history.dataPoints[0].pctSonnet7d!, 0.1, accuracy: 0.001)
    }
}
