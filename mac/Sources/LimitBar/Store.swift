// Lee data/latest.json cada 30 s y lanza el recolector con «Actualizar ahora».
import Foundation
import ServiceManagement

@MainActor
final class Store: ObservableObject {
    @Published private(set) var snapshot: Snapshot?
    @Published private(set) var refreshing = false
    @Published private(set) var now = Date()

    /// Carpeta del repo: la graba scripts/build_app.sh en el Info.plist (LBRepoPath).
    let repo: URL
    private var timer: Timer?

    static let staleMinutes = 45.0   // más de 2 rondas sin datos → aviso

    init() {
        let path = Bundle.main.object(forInfoDictionaryKey: "LBRepoPath") as? String
            ?? ProcessInfo.processInfo.environment["LIMITBAR_REPO"]
            ?? FileManager.default.currentDirectoryPath
        repo = URL(fileURLWithPath: path)
        reload()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.reload() }
        }
    }

    var dataURL: URL { repo.appendingPathComponent("data/latest.json") }

    var ageMinutes: Double? {
        snapshot?.collectedDate.map { now.timeIntervalSince($0) / 60 }
    }

    var isStale: Bool { (ageMinutes ?? .infinity) > Self.staleMinutes }

    func reload() {
        now = Date()
        snapshot = Snapshot.load(from: dataURL)
    }

    func refresh() {
        guard !refreshing else { return }
        refreshing = true
        let script = repo.appendingPathComponent("scripts/collect.sh")
        Task.detached {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/sh")
            p.arguments = [script.path]
            try? p.run()
            p.waitUntilExit()
            await MainActor.run {
                self.refreshing = false
                self.reload()
            }
        }
    }

    // MARK: Abrir al iniciar sesión

    var launchAtLogin: Bool {
        get { SMAppService.mainApp.status == .enabled }
        set {
            if newValue { try? SMAppService.mainApp.register() } else { try? SMAppService.mainApp.unregister() }
            objectWillChange.send()
        }
    }
}
