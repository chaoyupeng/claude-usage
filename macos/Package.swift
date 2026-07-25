// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "ClaudeUsageBar",
    defaultLocalization: "en",
    platforms: [
        .macOS(.v14)
    ],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.8.1")
    ],
    targets: [
        .executableTarget(
            name: "ClaudeUsageBar",
            dependencies: [
                .product(name: "Sparkle", package: "Sparkle")
            ],
            path: "Sources/ClaudeUsageBar",
            resources: [
                .process("Resources")
            ],
            linkerSettings: [
                .unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])
            ]
        ),
        .testTarget(
            name: "ClaudeUsageBarTests",
            dependencies: ["ClaudeUsageBar"],
            path: "Tests/ClaudeUsageBarTests",
            linkerSettings: [
                // The test bundle links Sparkle transitively, but without an
                // rpath of its own dyld can't find the framework and the bundle
                // fails to load — `swift test` dies before running a single
                // test. From the bundle's binary at
                // Foo.xctest/Contents/MacOS/Foo, three levels up is the build
                // products directory where Sparkle.framework sits.
                // (DYLD_FRAMEWORK_PATH is not a usable substitute: SIP strips
                // DYLD_* when spawning Apple-signed test helpers.)
                .unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@loader_path/../../.."])
            ]
        )
    ]
)
