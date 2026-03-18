import Foundation

private final class AppResourceBundleFinder {}

func claudeUsageBarResourceBundle(
    mainBundle: Bundle = .main,
    finderBundle: Bundle = Bundle(for: AppResourceBundleFinder.self)
) -> Bundle? {
    let bundleName = "ClaudeUsageBar_ClaudeUsageBar.bundle"
    let candidates: [URL?] = [
        mainBundle.resourceURL?.appendingPathComponent(bundleName),
        mainBundle.bundleURL.appendingPathComponent(bundleName),
        finderBundle.resourceURL?.appendingPathComponent(bundleName),
        mainBundle.executableURL?.deletingLastPathComponent().appendingPathComponent(bundleName),
    ]

    for case let candidate? in candidates {
        if let bundle = Bundle(url: candidate) {
            return bundle
        }
    }

    return nil
}
