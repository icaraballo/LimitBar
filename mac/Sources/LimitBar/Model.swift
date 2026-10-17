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

    var ok: Bool { status == "ok" }

    var name: String { Provider.name(id) }

    static func name(_ id: String) -> String {
        ["claude": "Claude", "gemini": "Gemini", "antigravity": "Antigravity", "chatgpt": "ChatGPT",
         "grok": "Grok", "deepseek": "DeepSeek", "muse": "Muse"][id] ?? id.capitalized
    }

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
