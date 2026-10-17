import json
import unittest
from pathlib import Path

from collector.main import collect
from collector.providers.base import Provider, ProviderError
from collector.providers.claude import parse_usage, read_access_token
from collector.schema import ProviderResult

FIXTURE = Path(__file__).parent / "fixtures" / "claude_usage.json"


class ParseUsageTest(unittest.TestCase):
    def test_fixture(self):
        windows = parse_usage(json.loads(FIXTURE.read_text()))
        self.assertEqual([w.id for w in windows], ["5h", "7d", "7d_sonnet"])
        self.assertEqual(windows[0].used_pct, 42.0)
        self.assertEqual(windows[0].resets_at, "2026-10-17T19:00:00Z")
        self.assertEqual(windows[1].used_pct, 18.4)

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
