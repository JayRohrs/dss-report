"""The sales pack (docs/sales): nothing invented, nothing over-claimed, the script really fits two minutes."""

import re
import unittest
from pathlib import Path

SALES = Path(__file__).resolve().parent.parent / "docs" / "sales"
FILES = ("README.md", "SELL_SHEET.md", "DEMO_SCRIPT.md", "OWNER_FAQ.md")
JARGON = ("odata", "guid", "phase ", "step code", "__count", "byte-order", "tsv")


def text(name):
    return (SALES / name).read_text(encoding="utf-8")


class SalesPack(unittest.TestCase):
    def test_all_four_documents_exist(self):
        for f in FILES:
            self.assertTrue((SALES / f).is_file(), f)

    def test_price_savings_and_return_are_unknown_placeholders(self):
        sheet = text("SELL_SHEET.md")
        for label in ("Price", "Savings", "Return on investment", "Customer references", "Support terms"):
            self.assertRegex(sheet, rf"\| {label} \| \*\*(UNKNOWN|None)\*\* \|")
        self.assertIn("Time saved: **UNKNOWN**", sheet)

    def test_no_money_figure_other_than_the_invented_cash_difference(self):
        for f in FILES:
            for m in re.finditer(r"\$\s?\d[\d,.]*", text(f)):
                self.assertEqual(m.group(0), "$23.50", f"{f}: {m.group(0)}")
            self.assertNotRegex(text(f), r"\d+\s?%", f)                    # no percentage claims
            self.assertNotRegex(text(f).lower(), r"\b\d+\s+(hours?|minutes?) (a|per|each) (day|week)", f)

    def test_the_honesty_promises_are_written_down(self):
        sheet = text("SELL_SHEET.md")
        for phrase in ("Could not tell", "never approves anything", "never touches Restaurant365",
                       "Nothing outstanding to approve.", "likely"):
            self.assertIn(phrase.lower(), sheet.lower())
        self.assertIn("invented", sheet)
        self.assertIn("Not made, endorsed or supported by Restaurant365", sheet)

    def test_the_sell_sheet_fits_one_page(self):
        self.assertLess(len(text("SELL_SHEET.md").split()), 600)

    def test_plain_words_no_jargon_in_the_sales_pack(self):
        for f in FILES:
            body = text(f).lower()
            for word in JARGON:
                if f == "README.md" and word == "tsv":
                    continue
                self.assertNotIn(word, body, f"{f}: {word}")

    def test_demo_script_timings_are_continuous_and_end_at_two_minutes(self):
        rows = re.findall(r"^\| (\d):(\d\d) – (\d):(\d\d) \|", text("DEMO_SCRIPT.md"), re.M)
        spans = [(int(a) * 60 + int(b), int(c) * 60 + int(d)) for a, b, c, d in rows]
        self.assertGreaterEqual(len(spans), 6)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], 120)
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertEqual(end, start)

    def test_demo_script_says_what_not_to_claim(self):
        script = text("DEMO_SCRIPT.md")
        self.assertIn("## Do not say", script)
        for claim in ("endorses", "real data", "Windows", "approve"):
            self.assertIn(claim, script.split("## Do not say")[1])

    def test_nothing_is_called_proven_that_is_not(self):
        everything = " ".join(text(f) for f in FILES).lower()
        self.assertIn("what its sign means is not yet confirmed", everything)
        self.assertNotRegex(everything, r"(negative|minus)[^.]{0,40}(means|is|=)\s+(short|over)")
        self.assertNotIn("100% accurate", everything)
        self.assertNotIn("auto-approv", everything.replace("automatic approval does not exist", ""))


if __name__ == "__main__":
    unittest.main()
