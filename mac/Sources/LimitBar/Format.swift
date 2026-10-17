// Textos en castellano: «hace 5 min», «reset 18:50 · en 2 h 08», colores por nivel.
import SwiftUI

enum Format {
    static func ago(_ minutes: Double) -> String {
        if minutes < 1 { return "ahora mismo" }
        if minutes < 60 { return "hace \(Int(minutes)) min" }
        return "hace \(Int(minutes) / 60) h \(Int(minutes) % 60) min"
    }

    static func until(_ date: Date, now: Date) -> String {
        let mins = Int(date.timeIntervalSince(now) / 60)
        if mins <= 0 { return "ya" }
        if mins < 60 { return "en \(mins) min" }
        let h = mins / 60, m = mins % 60
        if h < 24 { return String(format: "en %d h %02d", h, m) }
        return "en \(h / 24) d \(h % 24) h"
    }

    /// Hoy → «18:50»; esta semana → «jue 01:00»; más lejos → «5 nov».
    static func when(_ date: Date, now: Date) -> String {
        let cal = Calendar.current
        let f = DateFormatter()
        f.locale = Locale(identifier: "es_ES")
        if cal.isDate(date, inSameDayAs: now) {
            f.dateFormat = "HH:mm"
        } else if date.timeIntervalSince(now) < 6 * 86_400 {
            f.dateFormat = "EEE HH:mm"
        } else {
            f.dateFormat = "d MMM"
        }
        return f.string(from: date).replacingOccurrences(of: ".", with: "")
    }

    static func money(_ value: Double) -> String {
        value.rounded() == value ? "\(Int(value)) $" : String(format: "%.2f $", value)
    }

    static func color(_ pct: Double) -> Color {
        if pct >= 90 { return .red }
        if pct >= 70 { return .orange }
        return .accentColor
    }
}
