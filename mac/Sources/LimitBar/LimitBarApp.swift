// LimitBar.app: vive en la barra de menú (sin icono en el Dock). Al abrirla aparece arriba;
// «Salir» la cierra. Diseño provisional: el bueno sale de claude.ai.
import SwiftUI

@main
struct LimitBarApp: App {
    @StateObject private var store = Store()

    var body: some Scene {
        MenuBarExtra {
            MenuView().environmentObject(store)
        } label: {
            BarLabel(store: store)
        }
        .menuBarExtraStyle(.window)
    }
}

/// Icono fijo de la app (no un %: con varias IAs no se sabría de cuál es). Solo avisa si algo
/// pasa del 90 % o si los datos están viejos.
struct BarLabel: View {
    @ObservedObject var store: Store

    var body: some View {
        let critical = (store.snapshot?.worst?.usedPct ?? 0) >= 90
        Image(systemName: critical ? "exclamationmark.triangle.fill" : "gauge.with.dots.needle.67percent")
            .opacity(store.isStale ? 0.5 : 1)
    }
}

struct MenuView: View {
    @EnvironmentObject var store: Store
    @AppStorage("tab") private var tab = "claude"

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Picker("", selection: $tab) {
                ForEach(tabs, id: \.self) { Text(Provider.name($0)).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            if let provider = store.snapshot?.providers.first(where: { $0.id == tab }) {
                ProviderSection(provider: provider, now: store.now)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text(Provider.name(tab)).font(.headline)
                    Text(store.snapshot == nil ? "Sin datos todavía" : "Sin conectar todavía")
                        .foregroundStyle(.secondary)
                }
            }
            Divider()
            Footer()
        }
        .padding(14)
        .frame(width: 340)
        .onAppear { store.reload() }
    }
}

extension MenuView {
    /// Las fijas y, detrás, cualquier proveedor nuevo que traiga el JSON.
    var tabs: [String] {
        let extra = (store.snapshot?.providers.map(\.id) ?? []).filter { !Provider.tabs.contains($0) }
        return Provider.tabs + extra
    }
}

struct ProviderSection: View {
    let provider: Provider
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(provider.name).font(.headline)
            if !provider.ok {
                Label(provider.error ?? "Error", systemImage: "xmark.octagon")
                    .foregroundStyle(.red).font(.callout)
            } else {
                ForEach(provider.windows) { WindowRow(window: $0, now: now) }
                if let shares = provider.breakdown, !shares.isEmpty {
                    BreakdownView(shares: shares)
                }
            }
        }
    }
}

struct WindowRow: View {
    let window: Window
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(window.label)
                Spacer()
                Text(value).monospacedDigit().foregroundStyle(window.usedPct == nil ? .secondary : .primary)
            }
            .font(.callout)
            if let pct = window.usedPct {
                ProgressView(value: min(pct, 100), total: 100)
                    .tint(window.isCredit ? .green : Format.color(pct))
            }
            if let date = window.resetsDate {
                Text(detail(date)).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var value: String {
        if window.isCredit, let limit = window.limit {
            return "quedan \(Format.money(limit - (window.used ?? 0))) de \(Format.money(limit))"
        }
        return window.usedPct.map { "\(Int($0.rounded())) %" } ?? "sin dato"
    }

    private func detail(_ date: Date) -> String {
        let verb = window.isCredit ? "caduca" : "reset"
        return "\(verb) \(Format.when(date, now: now)) · \(Format.until(date, now: now))"
    }
}

struct BreakdownView: View {
    let shares: [Share]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Semanal por producto").font(.caption).foregroundStyle(.secondary)
            ForEach(shares) { s in
                HStack(spacing: 8) {
                    Text(s.label).frame(width: 90, alignment: .leading)
                    ProgressView(value: s.pct, total: 100).tint(.secondary)
                    Text("\(Int(s.pct)) %").monospacedDigit().frame(width: 36, alignment: .trailing)
                }
                .font(.caption)
            }
        }
        .padding(.top, 2)
    }
}

struct Footer: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if let age = store.ageMinutes {
                    Text("Actualizado \(Format.ago(age))" + (store.isStale ? " · ¿el Mac estuvo apagado?" : ""))
                } else {
                    Text("Sin hora de actualización")
                }
                Spacer()
                if store.refreshing {
                    ProgressView().controlSize(.small)
                } else {
                    Button { store.refresh() } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.borderless)
                        .help("Actualizar ahora")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            HStack {
                Toggle("Abrir al iniciar sesión", isOn: Binding(
                    get: { store.launchAtLogin },
                    set: { store.launchAtLogin = $0 }
                ))
                .toggleStyle(.checkbox)
                .font(.caption)
                Spacer()
                Button("Salir") { NSApplication.shared.terminate(nil) }
                    .keyboardShortcut("q")
            }
        }
    }
}
