// swift-tools-version:5.9
// App de la barra de menú del Mac. Se compila con scripts/build_app.sh (no hace falta Xcode).
import PackageDescription

let package = Package(
    name: "LimitBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "LimitBar", path: "Sources/LimitBar"),
    ]
)
