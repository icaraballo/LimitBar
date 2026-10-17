import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from collector import prices, usage_tokens

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def line(model, ts, mid, **usage):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    base.update(usage)
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"id": mid, "model": model, "usage": base}})


class PricesTest(unittest.TestCase):
    def test_normalize_strips_date(self):
        self.assertEqual(prices.normalize("claude-haiku-4-5-20251001"), "claude-haiku-4-5")

    def test_cost_opus_55(self):
        # 1M entrada ($4) + 1M salida ($20) + 1M lectura ($0.20) = $24.20
        usd = prices.cost_usd("claude-opus-5-5", 1_000_000, 1_000_000, 0, 0, 1_000_000)
        self.assertAlmostEqual(usd, 24.20, places=2)

    def test_cache_write_rates(self):
        # 1M a 5 min = $4*1.25 = $5 ; 1M a 1 h = $4*2 = $8
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", 0, 0, 1_000_000, 0, 0), 5.0, places=2)
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", 0, 0, 0, 1_000_000, 0), 8.0, places=2)

    def test_unknown_model(self):
        self.assertIsNone(prices.cost_usd("gpt-5", 1, 1, 0, 0, 0))


class ScanTest(unittest.TestCase):
    def _root(self, *lines):
        d = TemporaryDirectory()
        proj = Path(d.name) / "proj"
        proj.mkdir()
        (proj / "s.jsonl").write_text("\n".join(lines) + "\n")
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def test_aggregates_and_dedupes(self):
        root = self._root(
            line("claude-opus-5-5", "2026-10-17T10:00:00Z", "a", input_tokens=100, output_tokens=50),
            line("claude-opus-5-5", "2026-10-17T10:00:00Z", "a", input_tokens=100, output_tokens=50),  # dup
            line("claude-opus-5-5", "2026-10-17T11:00:00Z", "b", output_tokens=10),
        )
        rec = usage_tokens.scan(7, NOW, root)
        self.assertEqual(rec["claude-opus-5-5"], {"input": 100, "output": 60, "cw5m": 0, "cw1h": 0, "read": 0})

    def test_window_excludes_old(self):
        root = self._root(line("claude-opus-5-5", "2026-10-01T10:00:00Z", "old", input_tokens=999))
        self.assertEqual(usage_tokens.scan(7, NOW, root), {})

    def test_cache_creation_split(self):
        rec = usage_tokens.scan(7, NOW, self._root(json.dumps({
            "type": "assistant", "timestamp": "2026-10-17T10:00:00Z",
            "message": {"id": "x", "model": "claude-opus-5-5", "usage": {
                "input_tokens": 1, "output_tokens": 2,
                "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 40}}}})))
        self.assertEqual((rec["claude-opus-5-5"]["cw5m"], rec["claude-opus-5-5"]["cw1h"]), (30, 40))

    def test_read_cost_sorts_and_totals(self):
        root = self._root(
            line("claude-opus-5-5", "2026-10-17T10:00:00Z", "a", output_tokens=1_000_000),   # $20
            line("claude-haiku-4-5", "2026-10-17T10:00:00Z", "b", output_tokens=1_000_000),  # $5
        )
        cost = usage_tokens.read_cost(7, NOW, root)
        self.assertEqual([m.label for m in cost.models], ["Opus 5.5", "Haiku 4.5"])
        self.assertAlmostEqual(cost.priced_usd, 25.0, places=2)

    def test_calendar_periods_and_history_retention(self):
        # 2026-10-17 es sábado (semana natural desde lun 2026-10-12)
        root = self._root(
            line("claude-opus-5-5", "2026-10-17T10:00:00Z", "hoy", output_tokens=1_000_000),   # $20 hoy
            line("claude-opus-5-5", "2026-10-13T10:00:00Z", "sem", output_tokens=1_000_000),   # $20 martes
            line("claude-opus-5-5", "2026-10-03T10:00:00Z", "mes", output_tokens=1_000_000),   # $20 mes
        )
        with TemporaryDirectory() as tmp:
            hist_file = Path(tmp) / "cost_daily.json"
            # Simulamos un día de septiembre ya guardado en el histórico cuyos logs ya se borraron
            hist_file.write_text(json.dumps({
                "claude": {
                    "2026-09-15": {
                        "claude-opus-5-5": {"input": 0, "output": 1_000_000, "cw5m": 0, "cw1h": 0, "read": 0}
                    }
                }
            }))
            cost = usage_tokens.read_cost(7, NOW, root, history_file=hist_file)
            by_id = {p.id: p for p in cost.periods}
            self.assertEqual([p.id for p in cost.periods], ["day", "week", "month", "year"])
            self.assertEqual([p.label for p in cost.periods], ["Hoy", "Esta semana", "Octubre", "2026"])
            self.assertAlmostEqual(by_id["day"].priced_usd, 20.0, places=2)
            self.assertAlmostEqual(by_id["week"].priced_usd, 40.0, places=2)
            self.assertAlmostEqual(by_id["month"].priced_usd, 60.0, places=2)
            self.assertAlmostEqual(by_id["year"].priced_usd, 80.0, places=2)


if __name__ == "__main__":
    unittest.main()
