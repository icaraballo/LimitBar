import unittest
from datetime import datetime, timezone

from collector.providers.base import ProviderError
from collector.providers.gemini import _resolve_reset_iso, parse_usage_html

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)

# Texto real de gemini.google.com/usage (17-10-2026, Chrome en inglés). En el bloque semanal el %
# va detrás de la hora de reset.
REAL_EN = """Gemini
Usage limits
PRO

Your plan's limits determine how much you can use Gemini over time. Advanced models and features can take up more usage. Learn more

Updated just now

Current usage

0% used

Resets at 19:18

Weekly limit

Resets on 20 Oct at 08:18

2% used
"""


def local_iso(*args) -> str:
    """Hora local de este Mac → ISO UTC, como la devuelve el lector."""
    dt = datetime(*args).astimezone()
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class GeminiParseTest(unittest.TestCase):
    def test_real_page(self):
        windows = parse_usage_html(REAL_EN, now=NOW)
        self.assertEqual([(w.id, w.used_pct) for w in windows], [("5h", 0.0), ("7d", 2.0)])
        self.assertEqual(windows[1].resets_at, local_iso(2026, 10, 20, 8, 18))
        self.assertNotEqual(windows[0].resets_at, windows[1].resets_at)

    def test_spanish_page_with_credits(self):
        html = """
        <html><body>
          <h1>Límites de uso</h1>
          <div>Uso actual · 24 % usado · Se restablece a las 21:30</div>
          <div>Límite semanal · Se restablece el 20 oct a las 09:00 · 12 % usado</div>
          <div>Quedan 150 créditos</div>
        </body></html>
        """
        windows = parse_usage_html(html, now=NOW)
        self.assertEqual([(w.id, w.used_pct) for w in windows],
                         [("5h", 24.0), ("7d", 12.0), ("ai_credits", None)])
        self.assertEqual(windows[1].resets_at, local_iso(2026, 10, 20, 9, 0))
        self.assertEqual((windows[2].kind, windows[2].limit, windows[2].currency),
                         ("credit", 150.0, "créditos"))

    def test_weekly_block_still_loading(self):
        text = REAL_EN.split("Weekly limit")[0]
        windows = parse_usage_html(text, now=NOW)
        self.assertEqual([(w.id, w.used_pct) for w in windows], [("5h", 0.0), ("7d", None)])

    def test_logged_out_raises_provider_error(self):
        with self.assertRaisesRegex(ProviderError, "--login"):
            parse_usage_html("<html><body>Sign in to Google</body></html>", now=NOW)


class GeminiResetTest(unittest.TestCase):
    def test_weekday_and_am_pm(self):
        # 17-10-2026 es sábado: el próximo jueves es el 22.
        self.assertEqual(_resolve_reset_iso("Resets on Thu at 10:00 AM", now=NOW),
                         local_iso(2026, 10, 22, 10, 0))

    def test_month_first(self):
        self.assertEqual(_resolve_reset_iso("Resets on Oct 20 at 8:18 PM", now=NOW),
                         local_iso(2026, 10, 20, 20, 18))

    def test_january_seen_in_december_is_next_year(self):
        december = datetime(2026, 12, 30, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(_resolve_reset_iso("Resets on 2 Jan at 08:00", now=december),
                         local_iso(2027, 1, 2, 8, 0))


if __name__ == "__main__":
    unittest.main()
