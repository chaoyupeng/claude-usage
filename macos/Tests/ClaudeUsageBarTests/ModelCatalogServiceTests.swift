import XCTest
@testable import ClaudeUsageBar

@MainActor
final class ModelCatalogServiceTests: XCTestCase {

    private var cacheURL: URL!

    override func setUp() {
        super.setUp()
        cacheURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("models-\(UUID().uuidString).json")
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: cacheURL)
        super.tearDown()
    }

    /// Writes a catalog cache in the on-disk shape the service reads.
    private func writeCache(_ models: [CatalogModel], fetchedAt: Date = Date()) throws {
        struct Cached: Codable { var fetchedAt: Date; var models: [CatalogModel] }
        let data = try JSONEncoder().encode(Cached(fetchedAt: fetchedAt, models: models))
        try data.write(to: cacheURL)
    }

    private func service() -> ModelCatalogService {
        ModelCatalogService(session: .shared, cacheURL: cacheURL)
    }

    // MARK: - Cache loading

    func testLoadsDisplayNamesFromCache() throws {
        try writeCache([
            CatalogModel(id: "claude-opus-4-8", displayName: "Claude Opus 4.8"),
            CatalogModel(id: "claude-sonnet-5", displayName: "Claude Sonnet 5"),
        ])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "claude-opus-4-8"), "Claude Opus 4.8")
        XCTAssertEqual(catalog.displayName(for: "claude-sonnet-5"), "Claude Sonnet 5")
    }

    func testMissingCacheYieldsNoNames() {
        let catalog = service()  // nothing written
        XCTAssertNil(catalog.displayName(for: "claude-opus-4-8"))
        XCTAssertTrue(catalog.displayNames.isEmpty)
    }

    func testCorruptCacheIsIgnoredRatherThanCrashing() throws {
        try Data("not json at all".utf8).write(to: cacheURL)
        let catalog = service()
        XCTAssertTrue(catalog.displayNames.isEmpty)
        XCTAssertNil(catalog.displayName(for: "claude-opus-4-8"))
    }

    // MARK: - Lookup normalisation
    //
    // Logged IDs carry provider prefixes and long-context suffixes; the catalog
    // is keyed on bare IDs, so lookup has to normalise the same way pricing does.

    func testLookupStripsProviderPrefix() throws {
        try writeCache([CatalogModel(id: "claude-opus-4-1", displayName: "Claude Opus 4.1")])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "anthropic.claude-opus-4-1"), "Claude Opus 4.1")
        XCTAssertEqual(catalog.displayName(for: "us.anthropic.claude-opus-4-1"), "Claude Opus 4.1")
    }

    func testLookupStripsLongContextSuffix() throws {
        try writeCache([CatalogModel(id: "claude-opus-5", displayName: "Claude Opus 5")])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "claude-opus-5[1m]"), "Claude Opus 5")
    }

    func testLookupIsCaseInsensitive() throws {
        try writeCache([CatalogModel(id: "claude-opus-5", displayName: "Claude Opus 5")])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "CLAUDE-OPUS-5"), "Claude Opus 5")
    }

    func testUnknownModelFallsBackToNil() throws {
        // The UI renders the raw logged ID when this is nil, which is what it
        // did before the catalog existed.
        try writeCache([CatalogModel(id: "claude-opus-5", displayName: "Claude Opus 5")])
        let catalog = service()
        XCTAssertNil(catalog.displayName(for: "claude-something-unreleased"))
    }

    func testDatedIDResolvesToItsBaseCatalogEntry() throws {
        // Dated IDs extend a catalog entry rather than matching it. Without a
        // prefix fallback the UI would show the raw string for the canonical
        // Haiku 4.5 ID, which is dated.
        try writeCache([CatalogModel(id: "claude-haiku-4-5", displayName: "Claude Haiku 4.5")])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "claude-haiku-4-5-20251001"), "Claude Haiku 4.5")
    }

    func testPrefixFallbackPrefersTheMostSpecificEntry() throws {
        // A shorter key must not shadow a longer one that also matches.
        try writeCache([
            CatalogModel(id: "claude-opus-4", displayName: "Claude Opus 4"),
            CatalogModel(id: "claude-opus-4-8", displayName: "Claude Opus 4.8"),
        ])
        let catalog = service()
        XCTAssertEqual(catalog.displayName(for: "claude-opus-4-8-20260101"), "Claude Opus 4.8")
        XCTAssertEqual(catalog.displayName(for: "claude-opus-4-20250514"), "Claude Opus 4")
    }

    func testPrefixFallbackCombinesWithPrefixAndSuffixStripping() throws {
        try writeCache([CatalogModel(id: "claude-haiku-4-5", displayName: "Claude Haiku 4.5")])
        let catalog = service()
        XCTAssertEqual(
            catalog.displayName(for: "us.anthropic.claude-haiku-4-5-20251001[1m]"),
            "Claude Haiku 4.5"
        )
    }

    func testUnrelatedIDStillFallsBackToNil() throws {
        // The prefix fallback must not turn an unrelated ID into a wrong name.
        try writeCache([CatalogModel(id: "claude-haiku-4-5", displayName: "Claude Haiku 4.5")])
        let catalog = service()
        XCTAssertNil(catalog.displayName(for: "claude-opus-5"))
    }
}
