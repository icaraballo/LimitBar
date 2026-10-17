// El formato JSON v0 (collector/schema.py), tal cual lo escribe el recolector en data/latest.json.
import Foundation

struct Snapshot: Decodable {
    let collectedAt: String
    let sourceDevice: String
    let providers: [Provider]
}

struct Provider: Decodable, Identifiable {
    let id: String
    let status: String
    let error: String?
    let windows: [Window]
    let breakdown: [Share]?
    let cost: Cost?

    var ok: Bool { status == "ok" }

    var name: String { Provider.name(id) }

    static func name(_ id: String) -> String {
        ["claude": "Claude", "gemini": "Gemini", "antigravity": "Antigravity", "chatgpt": "ChatGPT",
         "grok": "Grok", "deepseek": "DeepSeek", "muse": "Muse"][id] ?? id.capitalized
    }

    /// App de escritorio de cada proveedor (comprobado con `osascript -e 'id of app "…"'`).
    /// Sin entrada o sin app instalada, la pestaña usa la inicial con su color.
    static let bundleIDs = ["claude": "com.anthropic.claudefordesktop", "gemini": "com.google.GeminiMacOS",
                            "antigravity": "com.google.antigravity"]

    /// Pestañas fijas: salen aunque el recolector aún no traiga ese proveedor.
    static let tabs = ["claude", "gemini", "antigravity"]
}

struct Window: Decodable, Identifiable {
    let id: String
    let label: String
    let usedPct: Double?
    let resetsAt: String?
    let kind: String?          // "limit" (o ausente) | "credit"
    let used: Double?
    let limit: Double?
    let currency: String?

    var isCredit: Bool { kind == "credit" }
    var resetsDate: Date? { resetsAt.flatMap(parseISO) }
}

struct Share: Decodable, Identifiable {
    let id: String
    let label: String
    let pct: Double
}

struct CostPeriod: Decodable, Identifiable {
    let id: String               // "day", "week", "month", "year"
    let label: String            // "Hoy", "Esta semana", "Octubre", "2026"
    let pricedUsd: Double
    let models: [ModelCost]
}

struct Cost: Decodable {
    let windowDays: Int
    let pricedUsd: Double
    let pricesRevised: String?
    let models: [ModelCost]
    let periods: [CostPeriod]?

    var hasAnyUsage: Bool {
        if let periods, !periods.isEmpty {
            return periods.contains { !$0.models.isEmpty }
        }
        return !models.isEmpty
    }
}

struct ModelCost: Decodable, Identifiable {
    let model: String
    let label: String
    let input: Int
    let output: Int
    let cacheWrite: Int
    let cacheRead: Int
    let costUsd: Double?

    var id: String { model }
    var totalTokens: Int { input + output + cacheWrite + cacheRead }
}

func parseISO(_ s: String) -> Date? {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = f.date(from: s) { return d }
    f.formatOptions = [.withInternetDateTime]
    return f.date(from: s)
}

extension Snapshot {
    static func load(from url: URL) -> Snapshot? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try? decoder.decode(Snapshot.self, from: data)
    }

    var collectedDate: Date? { parseISO(collectedAt) }

    /// La ventana más gastada de todas (los créditos no son límite): es la que manda.
    var worst: Window? {
        providers.filter(\.ok).flatMap(\.windows)
            .filter { !$0.isCredit && $0.usedPct != nil }
            .max { $0.usedPct! < $1.usedPct! }
    }
}
