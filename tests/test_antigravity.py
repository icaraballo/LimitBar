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
    """Con la respuesta real de GetUserStatus (17-10-2026), sin datos de la cuenta."""

    def test_one_window_per_family_in_order(self):
        windows = parse_usage(json.loads(FIXTURE.read_text()), now=NOW)
        self.assertEqual([w.id for w in windows],
                         ["flash_3_8", "argon_4", "opus_5_5", "sonnet_5_5", "gpt_oss_120b"])
        self.assertEqual((windows[0].used_pct, windows[0].resets_at), (6.6, "2026-10-17T17:59:34Z"))
        self.assertEqual(windows[1].used_pct, 70.1)
        self.assertEqual(windows[2].used_pct, 0.0)

    def test_period_comes_from_reset_time(self):
        windows = parse_usage(json.loads(FIXTURE.read_text()), now=NOW)
        self.assertEqual(windows[0].label, "Flash 3.8 · 5 h")
        self.assertEqual(windows[1].label, "Argon 4 · semanal")

    def test_omitted_remaining_fraction_means_100_pct_used(self):
        data = {"userStatus": {"cascadeModelConfigData": {"clientModelConfigs": [
            {"label": "Gemini 4 Argon (High)", "quotaInfo": {"resetTime": "2026-10-24T12:00:00Z"}},
        ]}}}
        windows = parse_usage(data, now=NOW)
        self.assertEqual((len(windows), windows[0].used_pct), (1, 100.0))

    def test_unknown_model_family_is_preserved(self):
        data = json.loads(FIXTURE.read_text())
        data["userStatus"]["cascadeModelConfigData"]["clientModelConfigs"].append({
            "label": "Gemini 5 Ultra (High)",
            "quotaInfo": {"remainingFraction": 0.25, "resetTime": "2026-10-17T20:00:00Z"},
        })
        ultra = [w for w in parse_usage(data, now=NOW) if w.id == "gemini_5_ultra"][0]
        self.assertEqual((ultra.label, ultra.used_pct), ("Gemini 5 Ultra · 5 h", 75.0))


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
