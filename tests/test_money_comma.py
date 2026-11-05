"""A comma in an amount is never guessed. 1,234.50 is a thousands mark; 23,50 might be a decimal mark, so it is
UNKNOWN with a visible warning instead of silently becoming 2350. Made-up values only."""

import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dssreport import dss_export as E


class ParseMoney(unittest.TestCase):
    def test_thousands_marks_still_read_as_before(self):
        for text, want in (("1,234.50", "1234.50"), ("-1,234.50", "-1234.50"), ("$1,234.50", "1234.50"),
                           ("(1,234.50)", "-1234.50"), ("1,234.50-", "-1234.50"), ("1,234,567.89", "1234567.89"),
                           ("3,000", "3000"), ("-23.50", "-23.50"), ("23.50", "23.50"), ("(23.50)", "-23.50"),
                           ("23.50-", "-23.50"), ("−23.50", "-23.50"), ("+5", "5"), ("0.0000", "0.0000")):
            self.assertEqual(E.parse_money(text), (Decimal(want), False), text)

    def test_a_comma_that_could_be_a_decimal_mark_is_unreadable_not_guessed(self):
        for text in ("-23,50", "23,50", "$23,50", "(23,50)", "23,50-", "1.234,50", "3000,00", "12,5", "1,23,456", ",50"):
            self.assertEqual(E.parse_money(text), (None, True), text)

    def test_blank_and_junk_unchanged(self):
        self.assertEqual(E.parse_money(""), (None, False))
        self.assertEqual(E.parse_money("n/a"), (None, True))
        self.assertEqual(E.parse_money("-"), (None, True))


def parse(over, sales="3000.00"):
    head = "Status,Location,Date,Net Sales,Over/Short\r\n"
    data = (head + f'In Progress,Sample Pier Grill,03/13/2026,"{sales}","{over}"\r\n').encode()
    rows, stats, _ = E.read_rows(data, "x.csv")
    return E.parse_export(rows, E.load_aliases(user=Path("/nonexistent/a.toml")), None,
                          datetime(2026, 3, 14, 8, 0), date(2026, 3, 14), stats)


class InTheFile(unittest.TestCase):
    def test_decimal_comma_over_short_is_unknown_with_a_visible_warning(self):
        p = parse("-23,50")
        self.assertIsNone(p.records[0].cash_over_short)
        self.assertTrue(any("comma that may be a decimal mark" in w for w in p.warnings))
        self.assertTrue(any("could not be read as a number" in w for w in p.warnings))

    def test_decimal_comma_net_sales_is_blank_with_the_same_warning(self):
        p = parse("0.00", sales="3000,00")
        self.assertIsNone(p.records[0].sales_total)
        self.assertTrue(any("comma that may be a decimal mark" in w for w in p.warnings))

    def test_thousands_comma_reads_with_no_comma_warning(self):
        p = parse("1,234.50", sales="3,000.00")
        self.assertEqual(p.records[0].cash_over_short, Decimal("1234.50"))
        self.assertEqual(p.records[0].sales_total, Decimal("3000.00"))
        self.assertFalse(any("comma" in w for w in p.warnings))

    def test_plain_23_50_with_a_dot_reads_normally(self):
        p = parse("23.50")
        self.assertEqual(p.records[0].cash_over_short, Decimal("23.50"))


if __name__ == "__main__":
    unittest.main()
