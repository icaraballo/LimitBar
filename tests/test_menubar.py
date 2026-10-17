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

    def test_no_data(self):
        self.assertTrue(render(None, NOW).startswith("LB ?"))


if __name__ == "__main__":
    unittest.main()
