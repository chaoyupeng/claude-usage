import Foundation
import AppKit
import Combine

/// A dotted release version, compared numerically rather than as a string
/// ("1.2.10" is newer than "1.2.9", which a lexical compare gets wrong).
struct ReleaseVersion: Comparable, CustomStringConvertible {
    let components: [Int]

    /// Parses "1.2.3" or "v1.2.3". Returns nil for anything that is not purely
    /// numeric components, so a pre-release or unexpected tag is ignored rather
    /// than mis-ranked.
    init?(_ raw: String) {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if text.hasPrefix("v") { text.removeFirst() }
        guard !text.isEmpty else { return nil }
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        var parsed: [Int] = []
        for part in parts {
            guard let value = Int(part), value >= 0 else { return nil }
            parsed.append(value)
        }
        guard !parsed.isEmpty else { return nil }
        components = parsed
    }

    var description: String { components.map(String.init).joined(separator: ".") }

    static func < (lhs: ReleaseVersion, rhs: ReleaseVersion) -> Bool {
        // Compare position by position, treating a missing component as 0 so
        // "1.2" and "1.2.0" rank equal.
        let count = max(lhs.components.count, rhs.components.count)
        for index in 0..<count {
            let left = index < lhs.components.count ? lhs.components[index] : 0
            let right = index < rhs.components.count ? rhs.components[index] : 0
            if left != right { return left < right }
        }
        return false
    }
}

/// An update the user has not yet dismissed.
struct AvailableUpdate: Equatable {
    let version: String
    let pageURL: URL
}

/// Checks GitHub Releases for a newer version and offers to open the download
/// page.
///
/// This app is not notarised, so it cannot install updates itself the way a
/// signed Sparkle feed would — it points the user at the release page and lets
/// them replace the app. That keeps the check to a single unauthenticated GET
/// with no request body and nothing about the user in it.
@MainActor
final class UpdateCheckService: ObservableObject {
    @Published private(set) var availableUpdate: AvailableUpdate?

    private let session: URLSession
    private let defaults: UserDefaults
    private let currentVersion: String
    private let latestReleaseAPI: URL
    private var isChecking = false

    /// Once a day is plenty for a menu bar app and keeps this off the usage
    /// refresh path. GitHub allows 60 unauthenticated requests an hour per IP,
    /// so this is nowhere near any limit.
    private static let checkInterval: TimeInterval = 60 * 60 * 24

    private static let lastCheckKey = "updateCheck.lastCheckedAt"
    private static let skippedVersionKey = "updateCheck.skippedVersion"

    init(
        session: URLSession = .shared,
        defaults: UserDefaults = .standard,
        currentVersion: String? = nil,
        latestReleaseAPI: URL = URL(string: "https://api.github.com/repos/chaoyupeng/claude-usage/releases/latest")!
    ) {
        self.session = session
        self.defaults = defaults
        self.currentVersion = currentVersion
            ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
            ?? "0"
        self.latestReleaseAPI = latestReleaseAPI
    }

    // MARK: - Decision logic

    /// Whether `latest` should be offered over `current`.
    ///
    /// Pure so the ranking is testable without network: an unparseable tag, a
    /// version the user skipped, or anything not strictly newer is not offered.
    nonisolated static func shouldOffer(latest: String, current: String, skipped: String?) -> Bool {
        guard let latestVersion = ReleaseVersion(latest),
              let currentVersion = ReleaseVersion(current),
              currentVersion < latestVersion
        else { return false }
        if let skipped, let skippedVersion = ReleaseVersion(skipped),
           !(skippedVersion < latestVersion) {
            return false  // already dismissed this version or newer
        }
        return true
    }

    // MARK: - Checking

    /// Checks if the daily interval has elapsed. Safe to call on every launch.
    func checkIfDue(force: Bool = false) {
        guard !isChecking else { return }
        if !force, let last = defaults.object(forKey: Self.lastCheckKey) as? Date,
           Date().timeIntervalSince(last) < Self.checkInterval {
            return
        }
        isChecking = true
        Task { [weak self] in
            await self?.check()
            self?.isChecking = false
        }
    }

    private func check() async {
        var request = URLRequest(url: latestReleaseAPI)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("ClaudeUsageBar/\(currentVersion)", forHTTPHeaderField: "User-Agent")

        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tag = json["tag_name"] as? String
            else { return }

            // Record the attempt only on success, so a network outage retries
            // on next launch instead of waiting out the interval.
            defaults.set(Date(), forKey: Self.lastCheckKey)

            let skipped = defaults.string(forKey: Self.skippedVersionKey)
            guard Self.shouldOffer(latest: tag, current: currentVersion, skipped: skipped) else { return }

            let page = (json["html_url"] as? String).flatMap(URL.init(string:))
                ?? URL(string: "https://github.com/chaoyupeng/claude-usage/releases/latest")!
            let update = AvailableUpdate(version: ReleaseVersion(tag)?.description ?? tag, pageURL: page)
            availableUpdate = update
            presentPrompt(for: update)
        } catch {
            return  // offline — try again next launch
        }
    }

    // MARK: - Prompt

    /// Shows the update prompt and acts on the choice.
    func presentPrompt(for update: AvailableUpdate) {
        let alert = NSAlert()
        alert.messageText = "Claude Usage \(update.version) is available"
        alert.informativeText = """
            You have \(currentVersion). Opening the download page will show the \
            latest release; replace the app in Applications to update.
            """
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Download")
        alert.addButton(withTitle: "Later")
        alert.addButton(withTitle: "Skip This Version")

        // A menu bar app has no window to attach a sheet to, and is normally not
        // frontmost, so activate first or the alert can appear behind other apps.
        NSApp.activate(ignoringOtherApps: true)

        switch alert.runModal() {
        case .alertFirstButtonReturn:
            NSWorkspace.shared.open(update.pageURL)
        case .alertThirdButtonReturn:
            defaults.set(update.version, forKey: Self.skippedVersionKey)
            availableUpdate = nil
        default:
            break  // Later: keep it in availableUpdate so the footer still shows it
        }
    }
}
