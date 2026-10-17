import unittest

from collector.schema import ProviderResult, Snapshot, Window
from collector.upload import build_rows


def snapshot() -> Snapshot:
    return Snapshot(
        collected_at="2026-10-17T15:00:00Z",
        source_device="macbook",
        providers=[
            ProviderResult(id="claude", windows=[
                Window("5h", "Sesión (5 h)", 38.0, "2026-10-17T16:50:00Z"),
                Window("7d", "Semanal", None, None),
            ]),
            ProviderResult.failed("gemini", "Sin sesión"),
        ],
    )


class BuildRowsTest(unittest.TestCase):
    def test_ok_provider(self):
        latest, history = build_rows(snapshot())
        claude = latest[0]
        self.assertEqual(claude["status"], "ok")
        self.assertEqual(claude["updated_at"], "2026-10-17T15:00:00Z")
        self.assertEqual(claude["windows"][0]["used_pct"], 38.0)

    def test_history_skips_empty_windows_and_errors(self):
        _, history = build_rows(snapshot())
        self.assertEqual([(h["provider"], h["window_id"]) for h in history], [("claude", "5h")])

    def test_error_keeps_last_good_data(self):
        latest, _ = build_rows(snapshot())
        gemini = latest[1]
        self.assertEqual(gemini["status"], "error")
        # sin windows ni updated_at: el upsert no pisa la última lectura buena
        self.assertNotIn("windows", gemini)
        self.assertNotIn("updated_at", gemini)


if __name__ == "__main__":
    unittest.main()
