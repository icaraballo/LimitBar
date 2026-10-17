import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from collector import usage_tokens
from collector.providers.antigravity import parse_usage

FIXTURE = Path(__file__).parent / "fixtures" / "antigravity_status.json"
NOW = datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc)


class AntigravityParseTest(unittest.TestCase):
    """Con la respuesta real de RetrieveUserQuotaSummary (17-10-2026)."""

    def test_groups_and_order_5h_before_weekly(self):
        windows = parse_usage(json.loads(FIXTURE.read_text()))
        self.assertEqual(
            [(w.id, w.label) for w in windows],
            [
                ("gemini_5h", "Gemini · 5 h"),
                ("gemini_7d", "Gemini · semanal"),
                ("claude_5h", "Claude · 5 h"),
                ("claude_7d", "Claude · semanal"),
                ("argon_4", "Argon 4 · semanal"),
            ],
        )
        self.assertEqual((windows[0].used_pct, windows[0].resets_at), (6.6, "2026-10-17T17:59:34Z"))
        self.assertEqual((windows[1].used_pct, windows[1].resets_at), (1.9, "2026-10-24T12:59:34Z"))
        self.assertEqual((windows[4].used_pct, windows[4].resets_at), (70.1, "2026-10-24T12:01:12Z"))

    def test_unused_bucket_has_no_reset_until_started(self):
        windows = {w.id: w for w in parse_usage(json.loads(FIXTURE.read_text()))}
        self.assertEqual((windows["claude_5h"].used_pct, windows["claude_5h"].resets_at), (0.0, None))
        self.assertEqual((windows["claude_7d"].used_pct, windows["claude_7d"].resets_at), (0.0, None))

        # Al empezar a usar el grupo, aparecen tanto el reset de 5 h como el semanal:
        data = json.loads(FIXTURE.read_text())
        for b in data["response"]["groups"][1]["buckets"]:
            b["remainingFraction"] = 0.9497072 if b["window"] == "5h" else 0.9748536
        started = {w.id: w for w in parse_usage(data)}
        self.assertEqual(
            (started["claude_5h"].used_pct, started["claude_5h"].resets_at),
            (5.0, "2026-10-17T21:51:12Z"),
        )
        self.assertEqual(
            (started["claude_7d"].used_pct, started["claude_7d"].resets_at),
            (2.5, "2026-10-24T16:51:12Z"),
        )

    def test_omitted_remaining_fraction_means_100_pct_used(self):
        data = {"response": {"groups": [{
            "displayName": "Gemini 4 Argon",
            "buckets": [{"bucketId": "gemini-argon-wtu-weekly", "window": "weekly",
                         "resetTime": "2026-10-24T12:00:00Z"}],
        }]}}
        windows = parse_usage(data)
        self.assertEqual((len(windows), windows[0].used_pct, windows[0].resets_at),
                         (1, 100.0, "2026-10-24T12:00:00Z"))

    def test_unknown_bucket_is_preserved(self):
        data = json.loads(FIXTURE.read_text())
        data["response"]["groups"].append({
            "displayName": "Gemini 5 Ultra",
            "buckets": [{
                "bucketId": "gemini-ultra-weekly",
                "window": "weekly",
                "remainingFraction": 0.25,
                "resetTime": "2026-10-24T20:00:00Z",
            }],
        })
        ultra = [w for w in parse_usage(data) if w.id == "gemini_ultra_weekly"][0]
        self.assertEqual((ultra.label, ultra.used_pct), ("Gemini 5 Ultra · semanal", 75.0))


class AntigravityTokensTest(unittest.TestCase):
    def test_scans_and_dedupes_transcripts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            log_dir = root / "conv-123" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)
            lines = [
                json.dumps({
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "content": "The user changed setting `Model Selection` from None to Gemini 4 Argon (High). "
                               "No need to comment on this change if the user doesn't ask about it.",
                }),
                json.dumps({
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-10-17T15:00:00Z",
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                    "cache_read_tokens": 0,
                }),
                # Duplicado del mismo paso: no debe contarse dos veces
                json.dumps({
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-10-17T15:00:00Z",
                    "input_tokens": 1_000_000,
                    "output_tokens": 1_000_000,
                    "cache_read_tokens": 0,
                }),
            ]
            (log_dir / "transcript.jsonl").write_text("\n".join(lines) + "\n")
            cost = usage_tokens.read_antigravity_cost(7, NOW, (root,))
            self.assertEqual(len(cost.models), 1)
            self.assertEqual(cost.models[0].label, "Argon 4")
            self.assertAlmostEqual(cost.priced_usd, 12.00, places=2)   # 1 MTok × 2 $ + 1 MTok × 10 $

    def test_model_name_with_dots(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            log_dir = root / "conv-789" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / "transcript.jsonl").write_text("\n".join([
                json.dumps({"step_index": 0, "type": "USER_INPUT", "content":
                            "The user changed setting `Model Selection` from None to Gemini 3.8 Flash "
                            "(High). No need to comment on this change if the user doesn't ask about it."}),
                json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE",
                            "created_at": "2026-10-17T15:00:00Z", "input_tokens": 10, "output_tokens": 10}),
            ]) + "\n")
            cost = usage_tokens.read_antigravity_cost(7, NOW, (root,))
            self.assertEqual(cost.models[0].label, "Flash 3.8")

    def test_tokens_before_model_selection_are_unpriced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            log_dir = root / "conv-456" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / "transcript.jsonl").write_text(json.dumps({
                "step_index": 0, "type": "PLANNER_RESPONSE", "created_at": "2026-10-17T15:00:00Z",
                "input_tokens": 1000, "output_tokens": 1000,
            }) + "\n")
            cost = usage_tokens.read_antigravity_cost(7, NOW, (root,))
            self.assertEqual((cost.models[0].model, cost.models[0].cost_usd), ("desconocido", None))
            self.assertEqual(cost.priced_usd, 0)


if __name__ == "__main__":
    unittest.main()
