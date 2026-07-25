import XCTest
@testable import ClaudeUsageBar

/// The guard exits the process when it fires, so a false positive means the app
/// refuses to launch at all — worse than the duplicate icons it prevents. These
/// pin the conservative direction of every edge case.
final class SingleInstanceGuardTests: XCTestCase {

    private let me: pid_t = 1000

    func testKeepsRunningWhenOnlySelfIsPresent() {
        let instances = [RunningInstance(pid: me, isTerminated: false)]
        XCTAssertFalse(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))
    }

    func testKeepsRunningWhenNothingIsListed() {
        // An empty list means the lookup told us nothing — never a reason to exit.
        XCTAssertFalse(SingleInstanceGuard.shouldYield(currentPID: me, instances: []))
    }

    func testKeepsRunningWhenSelfAppearsTwice() {
        // Guards the worst failure mode: seeing our own process twice and
        // terminating on launch every time.
        let instances = [
            RunningInstance(pid: me, isTerminated: false),
            RunningInstance(pid: me, isTerminated: false),
        ]
        XCTAssertFalse(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))
    }

    func testKeepsRunningWhenTheOtherInstanceHasTerminated() {
        // A straggler that has already exited must not block startup.
        let instances = [
            RunningInstance(pid: me, isTerminated: false),
            RunningInstance(pid: 2000, isTerminated: true),
        ]
        XCTAssertFalse(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))
    }

    func testYieldsToALiveOtherInstance() {
        let instances = [
            RunningInstance(pid: me, isTerminated: false),
            RunningInstance(pid: 2000, isTerminated: false),
        ]
        XCTAssertTrue(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))
    }

    func testYieldsWhenTheOtherInstanceIsListedAlone() {
        // The existing copy is running and we are not in the list yet.
        let instances = [RunningInstance(pid: 2000, isTerminated: false)]
        XCTAssertTrue(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))
    }

    func testYieldsOnlyForTheLiveInstanceAmongMany() {
        let instances = [
            RunningInstance(pid: me, isTerminated: false),
            RunningInstance(pid: 2000, isTerminated: true),
            RunningInstance(pid: 3000, isTerminated: true),
        ]
        XCTAssertFalse(SingleInstanceGuard.shouldYield(currentPID: me, instances: instances))

        let withLiveOne = instances + [RunningInstance(pid: 4000, isTerminated: false)]
        XCTAssertTrue(SingleInstanceGuard.shouldYield(currentPID: me, instances: withLiveOne))
    }
}
