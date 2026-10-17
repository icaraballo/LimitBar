import unittest
from datetime import datetime, timezone

from menubar.render import render

NOW = datetime(2026, 10, 17, 14, 30, tzinfo=timezone.utc)


def data(collected="2026-10-17T14:28:00Z", providers=None):
    return {
        "schema_version": 0,
        "collected_at": collected,
        "source_device": "mac",
        "providers": providers if providers is not None else [{
            "id": "claude", "status": "ok", "error": None,
            "windows": [
                {"id": "5h", "label": "Sesión (5 h)", "used_pct": 45.0, "resets_at": "2026-10-17T16:50:00Z"},
                {"id": "7d", "label": "Semanal", "used_pct": 14.0, "resets_at": "2026-10-21T23:00:00Z"},
            ],
        }],
    }


class RenderTest(unittest.TestCase):
    def test_title_is_worst_window(self):
        title = render(data(), NOW).splitlines()[0]
        self.assertTrue(title.startswith("45%"))
        self.assertNotIn("color=", title)

    def test_menu_lists_windows_and_freshness(self):
        out = render(data(), NOW)
        self.assertIn("Claude", out)
        self.assertIn("Semanal", out)
        self.assertIn("en 2 h 20", out)
        self.assertIn("Actualizado hace 2 min", out)

    def test_high_usage_is_red(self):
        d = data()
        d["providers"][0]["windows"][0]["used_pct"] = 95.0
        self.assertIn("color=#e5484d", render(d, NOW).splitlines()[0])

    def test_stale_data_is_flagged(self):
        out = render(data(collected="2026-10-17T12:00:00Z"), NOW)
        self.assertIn("⏸", out.splitlines()[0])
        self.assertIn("¿el Mac estuvo apagado?", out)

    def test_provider_error(self):
        out = render(data(providers=[{"id": "gemini", "status": "error",
                                      "error": "Sin sesión", "windows": []}]), NOW)
        self.assertTrue(out.startswith("LB ✗"))
        self.assertIn("✗ Sin sesión", out)

    def test_credit_is_not_the_title(self):
        d = data()
        d["providers"][0]["windows"].append({
            "id": "cloud_credits", "label": "Créditos nube", "used_pct": 80.0,
            "resets_at": "2026-11-05T07:59:00Z", "kind": "credit", "used": 80.0, "limit": 100.0,
            "currency": "USD"})
        d["providers"][0]["breakdown"] = [{"id": "chat", "label": "Chats", "pct": 13.0}]
        out = render(d, NOW)
        self.assertTrue(out.startswith("45%"))
        self.assertIn("20 $", out)
        self.assertIn("Semanal por producto", out)

    def test_credits_without_money_or_pct(self):
        d = data()
        d["providers"][0]["windows"].append({
            "id": "ai_credits", "label": "Créditos IA", "used_pct": None, "resets_at": None,
            "kind": "credit", "used": None, "limit": 150.0, "currency": "créditos"})
        out = render(d, NOW)
        self.assertIn("quedan 150 créditos", out)
        self.assertNotIn("150 $", out)

    def test_no_data(self):
        self.assertTrue(render(None, NOW).startswith("LB ?"))


if __name__ == "__main__":
    unittest.main()
