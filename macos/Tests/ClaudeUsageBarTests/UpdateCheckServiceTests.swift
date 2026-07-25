import XCTest
@testable import ClaudeUsageBar

final class UpdateCheckServiceTests: XCTestCase {

    // MARK: - Version parsing and ordering

    func testParsesPlainAndPrefixedTags() {
        XCTAssertEqual(ReleaseVersion("1.2.3")?.description, "1.2.3")
        XCTAssertEqual(ReleaseVersion("v1.2.3")?.description, "1.2.3")
        XCTAssertEqual(ReleaseVersion("V1.2.3")?.description, "1.2.3")
        XCTAssertEqual(ReleaseVersion(" v1.2.3 ")?.description, "1.2.3")
    }

    func testRejectsNonNumericTags() {
        // Better to ignore a tag we cannot rank than to guess at its order.
        for tag in ["", "v", "1.2.3-beta", "nightly", "1.2.x", "v1..2", "-1.0.0"] {
            XCTAssertNil(ReleaseVersion(tag), tag)
        }
    }

    func testOrdersNumericallyNotLexically() {
        // The case a string compare gets wrong.
        XCTAssertTrue(ReleaseVersion("1.2.9")! < ReleaseVersion("1.2.10")!)
        XCTAssertTrue(ReleaseVersion("1.9.0")! < ReleaseVersion("1.10.0")!)
        XCTAssertTrue(ReleaseVersion("9.0.0")! < ReleaseVersion("10.0.0")!)
    }

    func testMissingComponentsCountAsZero() {
        XCTAssertFalse(ReleaseVersion("1.2")! < ReleaseVersion("1.2.0")!)
        XCTAssertFalse(ReleaseVersion("1.2.0")! < ReleaseVersion("1.2")!)
        XCTAssertTrue(ReleaseVersion("1.2")! < ReleaseVersion("1.2.1")!)
    }

    // MARK: - Whether to offer an update

    private func shouldOffer(_ latest: String, over current: String, skipped: String? = nil) -> Bool {
        UpdateCheckService.shouldOffer(latest: latest, current: current, skipped: skipped)
    }

    func testOffersOnlyStrictlyNewerVersions() {
        XCTAssertTrue(shouldOffer("v1.2.4", over: "1.2.3"))
        XCTAssertTrue(shouldOffer("v2.0.0", over: "1.9.9"))
        XCTAssertFalse(shouldOffer("v1.2.3", over: "1.2.3"), "same version")
        XCTAssertFalse(shouldOffer("v1.2.2", over: "1.2.3"), "older release")
    }

    func testDoesNotOfferWhenEitherVersionIsUnrankable() {
        XCTAssertFalse(shouldOffer("nightly", over: "1.2.3"))
        XCTAssertFalse(shouldOffer("v1.3.0-rc1", over: "1.2.3"))
        XCTAssertFalse(shouldOffer("v1.2.4", over: "not-a-version"))
    }

    func testSkippedVersionIsNotOfferedAgain() {
        XCTAssertFalse(shouldOffer("v1.2.4", over: "1.2.3", skipped: "1.2.4"))
    }

    func testSkippingDoesNotSuppressALaterVersion() {
        // Skipping 1.2.4 must not hide 1.2.5 — otherwise one dismissal silences
        // every future update.
        XCTAssertTrue(shouldOffer("v1.2.5", over: "1.2.3", skipped: "1.2.4"))
    }

    func testSkippingANewerVersionSuppressesAnOlderOne() {
        // Defensive: if a release is pulled and the "latest" tag goes backwards,
        // a version already dismissed should stay dismissed.
        XCTAssertFalse(shouldOffer("v1.2.4", over: "1.2.3", skipped: "1.2.5"))
    }

    func testUnrankableSkipMarkerIsIgnored() {
        // A junk stored value must not block legitimate updates.
        XCTAssertTrue(shouldOffer("v1.2.4", over: "1.2.3", skipped: "garbage"))
    }
}
