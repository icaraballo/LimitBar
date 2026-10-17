import json
import unittest
from pathlib import Path

from collector.main import collect
from collector.providers.base import Provider, ProviderError
from collector.providers.claude import parse_breakdown, parse_usage, read_access_token
from collector.schema import ProviderResult

FIXTURE = Path(__file__).parent / "fixtures" / "claude_usage.json"


class ParseUsageTest(unittest.TestCase):
    def test_fixture(self):
        windows = parse_usage(json.loads(FIXTURE.read_text()))
        self.assertEqual([w.id for w in windows], ["5h", "7d", "7d_sonnet", "cloud_credits"])
        self.assertEqual(windows[0].used_pct, 42.0)
        self.assertEqual(windows[0].resets_at, "2026-10-17T19:00:00Z")
        self.assertEqual(windows[1].used_pct, 18.4)

    def test_unknown_model_window_is_kept(self):
        data = json.loads(FIXTURE.read_text())
        data["seven_day_fable"] = {"utilization": 61.0, "resets_at": "2026-10-21T07:00:00Z"}
        data["seven_day_haiku"] = None
        data["extra_usage"] = {"is_enabled": False, "utilization": None}
        fable = [w for w in parse_usage(data) if w.id == "7d_fable"][0]
        self.assertEqual((fable.id, fable.label, fable.used_pct), ("7d_fable", "Semanal · Fable", 61.0))
        self.assertEqual(len(parse_usage(data)), 5)

    def test_dollar_credit(self):
        credit = parse_usage(json.loads(FIXTURE.read_text()))[-1]
        self.assertEqual((credit.label, credit.kind), ("Créditos nube", "credit"))
        self.assertEqual((credit.used, credit.limit, credit.currency), (25.0, 100.0, "USD"))
        self.assertEqual(credit.resets_at, "2026-11-05T07:59:00Z")

    def test_limits_have_no_money(self):
        five_hour = parse_usage(json.loads(FIXTURE.read_text()))[0]
        self.assertEqual((five_hour.kind, five_hour.limit), ("limit", None))

    def test_breakdown(self):
        shares = parse_breakdown(json.loads(FIXTURE.read_text()))
        self.assertEqual([(s.label, s.pct) for s in shares][:2], [("Claude Code", 52.0), ("Chats", 13.0)])
        self.assertEqual(shares[-1].label, "Otros")
        self.assertEqual(parse_breakdown({}), [])

    def test_main_windows_always_present(self):
        windows = parse_usage({})
        self.assertEqual([(w.id, w.used_pct) for w in windows], [("5h", None), ("7d", None)])


class TokenTest(unittest.TestCase):
    def test_expired(self):
        blob = json.dumps({"claudeAiOauth": {"accessToken": "x", "expiresAt": 1000}})
        with self.assertRaisesRegex(ProviderError, "renovar la sesión"):
            read_access_token(blob, now_ms=2000)

    def test_no_claude_session(self):
        with self.assertRaises(ProviderError):
            read_access_token(json.dumps({"mcpOAuth": {}}))

    def test_valid(self):
        blob = json.dumps({"claudeAiOauth": {"accessToken": "abc", "expiresAt": 5000}})
        self.assertEqual(read_access_token(blob, now_ms=1000), "abc")


class Boom(Provider):
    id = "boom"

    def fetch(self) -> ProviderResult:
        raise RuntimeError("explota")


class Fine(Provider):
    id = "fine"

    def fetch(self) -> ProviderResult:
        return ProviderResult(id=self.id)


class IsolationTest(unittest.TestCase):
    def test_failing_provider_does_not_break_others(self):
        snap = collect([Boom(), Fine()])
        boom, fine = snap.providers
        self.assertEqual(boom.status, "error")
        self.assertIn("RuntimeError", boom.error)
        self.assertEqual(fine.status, "ok")


if __name__ == "__main__":
    unittest.main()
