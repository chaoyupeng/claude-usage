import XCTest
@testable import ClaudeUsageBar

final class MenuBarIconRendererTests: XCTestCase {
    func testRenderIconReturnsNonZeroSize() {
        let image = renderIcon(pct5h: 0.5, pct7d: 0.5)
        XCTAssertGreaterThan(image.size.width, 0)
        XCTAssertGreaterThan(image.size.height, 0)
    }

    func testRenderIconIsTemplate() {
        let image = renderIcon(pct5h: 0.5, pct7d: 0.5)
        XCTAssertTrue(image.isTemplate)
    }

    func testRenderIconClampsPctAtZero() {
        // Should not crash with negative values
        let image = renderIcon(pct5h: -0.5, pct7d: -0.5)
        XCTAssertGreaterThan(image.size.width, 0)
    }

    func testRenderIconClampsPctAboveOne() {
        // Should not crash with values > 1
        let image = renderIcon(pct5h: 1.5, pct7d: 1.5)
        XCTAssertGreaterThan(image.size.width, 0)
    }

    func testRenderUnauthenticatedIconIsTemplate() {
        let image = renderUnauthenticatedIcon()
        XCTAssertTrue(image.isTemplate)
    }

    func testRenderUnauthenticatedIconHasSameSizeAsAuthenticated() {
        let auth = renderIcon(pct5h: 0.5, pct7d: 0.5)
        let unauth = renderUnauthenticatedIcon()
        XCTAssertEqual(auth.size.width, unauth.size.width, accuracy: 0.01)
        XCTAssertEqual(auth.size.height, unauth.size.height, accuracy: 0.01)
    }
}
