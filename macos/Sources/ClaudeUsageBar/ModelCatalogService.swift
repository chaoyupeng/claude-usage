import Foundation
import Combine

/// One model as described by the Models API.
struct CatalogModel: Codable, Equatable {
    let id: String
    let displayName: String
}

/// Cached catalog plus the time it was fetched.
private struct CachedCatalog: Codable {
    var fetchedAt: Date
    var models: [CatalogModel]
}

/// Keeps model display names current by reading them from the Models API,
/// instead of hardcoding a name for every model in the binary.
///
/// Only names and IDs come from the API — it does not publish pricing, so rates
/// stay in `CostEstimator`. Everything here degrades quietly: with no cache and
/// no network the UI falls back to the raw model ID, which is what it showed
/// before this existed.
@MainActor
final class ModelCatalogService: ObservableObject {
    /// Display name per normalised model ID.
    @Published private(set) var displayNames: [String: String] = [:]

    private let credentialsStore: StoredCredentialsStore
    private let session: URLSession
    private let cacheURL: URL
    private var isFetching = false

    /// Model metadata changes on the order of weeks, so one fetch a day is
    /// plenty and keeps this off the refresh path.
    private static let refreshInterval: TimeInterval = 60 * 60 * 24

    private static let endpoint = URL(string: "https://api.anthropic.com/v1/models")!

    init(
        credentialsStore: StoredCredentialsStore = StoredCredentialsStore(),
        session: URLSession = .shared,
        cacheURL: URL? = nil
    ) {
        self.credentialsStore = credentialsStore
        self.session = session
        self.cacheURL = cacheURL ?? FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent(".config/claude-usage-bar/models.json")
        loadCache()
    }

    /// Display name for a logged model ID, or nil to fall back to the raw ID.
    ///
    /// Logged IDs carry provider prefixes and long-context suffixes, so they are
    /// normalised the same way the rate lookup normalises them. Dated IDs
    /// (`claude-haiku-4-5-20251001`) extend a catalog entry rather than matching
    /// it, so an exact miss falls back to the longest catalog key the ID starts
    /// with — the same rule the rate lookup applies.
    func displayName(for loggedModelID: String) -> String? {
        let id = CostEstimator.normalizedModelID(loggedModelID)
        if let exact = displayNames[id] { return exact }
        return displayNames
            .filter { id.hasPrefix($0.key) }
            .max { $0.key.count < $1.key.count }?
            .value
    }

    /// Fetches the catalog if the cache is missing or stale. Safe to call often.
    func refreshIfStale() {
        guard !isFetching else { return }
        if let fetchedAt = cachedFetchDate,
           Date().timeIntervalSince(fetchedAt) < Self.refreshInterval {
            return
        }
        isFetching = true
        Task { [weak self] in
            await self?.fetch()
            self?.isFetching = false
        }
    }

    // MARK: - Fetching

    private func fetch() async {
        // Uses the stored token as-is rather than driving a refresh: a stale
        // token just means the cache stays put until the next attempt, and
        // model names are not worth forcing a token refresh for.
        guard let credentials = credentialsStore.load(defaultScopes: []),
              !credentials.isExpired() else { return }

        var collected: [CatalogModel] = []
        var afterID: String?

        // The endpoint paginates; follow it so a future long model list is not
        // silently truncated to the first page.
        for _ in 0..<10 {
            guard var components = URLComponents(url: Self.endpoint, resolvingAgainstBaseURL: false) else { return }
            var query = [URLQueryItem(name: "limit", value: "100")]
            if let afterID { query.append(URLQueryItem(name: "after_id", value: afterID)) }
            components.queryItems = query
            guard let url = components.url else { return }

            var request = URLRequest(url: url)
            request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
            request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
            request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")

            do {
                let (data, response) = try await session.data(for: request)
                guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                      let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let page = json["data"] as? [[String: Any]]
                else { return }

                for entry in page {
                    guard let id = entry["id"] as? String,
                          let name = entry["display_name"] as? String else { continue }
                    collected.append(CatalogModel(id: id.lowercased(), displayName: name))
                }

                guard json["has_more"] as? Bool == true,
                      let lastID = json["last_id"] as? String else { break }
                afterID = lastID
            } catch {
                return  // offline or refused — keep whatever the cache holds
            }
        }

        guard !collected.isEmpty else { return }
        apply(collected)
        saveCache(CachedCatalog(fetchedAt: Date(), models: collected))
    }

    private func apply(_ models: [CatalogModel]) {
        displayNames = Dictionary(
            models.map { ($0.id, $0.displayName) },
            uniquingKeysWith: { first, _ in first }
        )
    }

    // MARK: - Cache

    private var cachedFetchDate: Date?

    private func loadCache() {
        guard let data = try? Data(contentsOf: cacheURL),
              let cached = try? JSONDecoder().decode(CachedCatalog.self, from: data)
        else { return }
        cachedFetchDate = cached.fetchedAt
        apply(cached.models)
    }

    private func saveCache(_ catalog: CachedCatalog) {
        cachedFetchDate = catalog.fetchedAt
        do {
            try FileManager.default.createDirectory(
                at: cacheURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try JSONEncoder().encode(catalog).write(to: cacheURL, options: .atomic)
        } catch {
            // A cache write failure only costs a refetch next launch.
        }
    }
}
