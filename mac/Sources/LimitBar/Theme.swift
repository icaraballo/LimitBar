// Aspecto del popover: icono de cada app (pedido a macOS, no se copian logos), pestañas y temas.
import AppKit
import SwiftUI

@MainActor
enum AppIcons {
    private static var cache: [String: NSImage?] = [:]

    /// Icono de la app instalada del proveedor, o nil si no hay. Se pide una sola vez.
    static func icon(for provider: String) -> NSImage? {
        if let hit = cache[provider] { return hit }
        var icon: NSImage?
        if let bundleID = Provider.bundleIDs[provider],
           let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) {
            icon = NSWorkspace.shared.icon(forFile: url.path)
            icon?.size = NSSize(width: 18, height: 18)
        }
        cache[provider] = icon
        return icon
    }

    /// Color del respaldo (casilla con la inicial).
    static func tint(_ provider: String) -> Color {
        let hex: [String: UInt32] = ["claude": 0xD97757, "gemini": 0x4285F4, "antigravity": 0x34A853,
                                     "chatgpt": 0x10A37F, "grok": 0x555555, "deepseek": 0x4D6BFE]
        let v = hex[provider] ?? 0x8E8E93
        return Color(red: Double(v >> 16 & 0xFF) / 255, green: Double(v >> 8 & 0xFF) / 255,
                     blue: Double(v & 0xFF) / 255)
    }
}

struct ProviderIcon: View {
    let provider: String

    var body: some View {
        if let image = AppIcons.icon(for: provider) {
            Image(nsImage: image).resizable().frame(width: 18, height: 18)
        } else {
            RoundedRectangle(cornerRadius: 5)
                .fill(AppIcons.tint(provider))
                .frame(width: 18, height: 18)
                .overlay(Text(Provider.name(provider).prefix(1)).font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.white))
        }
    }
}

/// Pestañas a todo el ancho con icono + nombre (el Picker segmentado no pinta bien iconos).
struct ProviderTabs: View {
    let tabs: [String]
    @Binding var selection: String
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: 2) {
            ForEach(tabs, id: \.self) { id in
                let selected = id == selection
                Button { selection = id } label: {
                    HStack(spacing: 5) {
                        ProviderIcon(provider: id)
                        Text(Provider.name(id)).fontWeight(selected ? .semibold : .regular)
                            .lineLimit(1)
                    }
                    .font(.callout)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 5)
                    .background {
                        if selected {
                            RoundedRectangle(cornerRadius: 7)
                                .fill(scheme == .dark ? Color.white.opacity(0.2) : .white)
                                .shadow(color: .black.opacity(0.12), radius: 2, y: 1)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 9).fill(Color.primary.opacity(0.06)))
    }
}

/// Fondo semitransparente: blanco roto en claro, gris (no negro) en oscuro.
struct PopoverBackground: View {
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ZStack {
            Rectangle().fill(.ultraThinMaterial)
            if scheme == .dark {
                Color(red: 0x2E / 255, green: 0x2E / 255, blue: 0x34 / 255).opacity(0.92)
            } else {
                Color(red: 0xF6 / 255, green: 0xF6 / 255, blue: 0xF9 / 255).opacity(0.84)
            }
        }
        .ignoresSafeArea()
    }
}

/// Barra de progreso propia: la pista cambia con el tema (negro 8 % / blanco 12 %).
struct Bar: View {
    let value: Double          // 0…100
    let tint: Color
    var height: CGFloat = 5
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(scheme == .dark ? Color.white.opacity(0.12) : Color.black.opacity(0.08))
                Capsule().fill(tint).frame(width: geo.size.width * min(max(value, 0), 100) / 100)
            }
        }
        .frame(height: height)
    }
}

/// Ajuste «Automático / Claro / Oscuro».
enum Appearance: String, CaseIterable, Identifiable {
    case auto, light, dark
    var id: String { rawValue }
    var label: String { ["auto": "Automático", "light": "Claro", "dark": "Oscuro"][rawValue]! }
    var scheme: ColorScheme? { self == .light ? .light : self == .dark ? .dark : nil }
}
