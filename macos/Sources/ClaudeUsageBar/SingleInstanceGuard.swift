import AppKit

/// One running copy of the app, reduced to just what the guard decides on.
struct RunningInstance: Equatable {
    let pid: pid_t
    let isTerminated: Bool
}

/// Stops a second copy of the app running alongside the first.
///
/// macOS does not prevent this on its own: two bundles at different paths share
/// the identifier `com.local.ClaudeUsageBar`, so a build run from the repo
/// launches happily beside the copy in /Applications — and because the app is a
/// login item, one is normally already running. The result is two menu bar
/// icons, each with its own popover, which reads as the UI losing state when you
/// click the "wrong" one.
enum SingleInstanceGuard {

    /// Whether this process should stand down in favour of an existing instance.
    ///
    /// Kept free of AppKit so it can be tested directly: getting this wrong means
    /// the app refuses to launch at all, which is far worse than two icons.
    /// Deliberately conservative — it yields only for a *live* instance with a
    /// *different* pid, so a duplicate entry for our own process, a terminated
    /// straggler, or an empty list all mean "keep running".
    static func shouldYield(currentPID: pid_t, instances: [RunningInstance]) -> Bool {
        instances.contains { $0.pid != currentPID && !$0.isTerminated }
    }

    /// Activates an already-running instance and returns true if this process
    /// should exit. No-ops when the bundle identifier is unavailable.
    @MainActor
    static func yieldToExistingInstance() -> Bool {
        guard let bundleID = Bundle.main.bundleIdentifier else { return false }

        let running = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
        let currentPID = ProcessInfo.processInfo.processIdentifier

        let instances = running.map {
            RunningInstance(pid: $0.processIdentifier, isTerminated: $0.isTerminated)
        }
        guard shouldYield(currentPID: currentPID, instances: instances) else { return false }

        // Bring the survivor forward so launching feels like a no-op rather than
        // nothing happening at all.
        running
            .first { $0.processIdentifier != currentPID && !$0.isTerminated }?
            .activate()

        return true
    }
}
