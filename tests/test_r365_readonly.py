"""Read-only R365 connector: same shape as the mock, GET only, missing fields UNKNOWN.
Made-up fixtures and a local mock server only; nothing here touches a real R365 tenant."""

import dataclasses
import http.client
import json
import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from dssreport.adapters.demo import DemoAdapter
from dssreport.credstore import InMemoryStoreForTests
from dssreport.model import DayRecord
from dssreport.r365 import Mapping
from dssreport.r365_readonly import R365ReadOnlySource, load_documented_fields, unknown_fields
from dssreport.settings import Instance, Settings, validate
from dssreport.sources import DataSource, build_source

from .mock_r365 import MAPPING, PASSWORD, USER, MockR365, rows

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / "tests/fixtures/r365_readonly/made_up_rows.json").read_text())["value"]
DAY = date(2026, 3, 13)


def make(server, documented=None, **kw):
    inst = Instance(id="main", name="Sample Group A", base_url=server.url, username=USER,
                    source_kind="r365-readonly")
    store = InMemoryStoreForTests()
    store.set(inst.credential_key, PASSWORD)
    return R365ReadOnlySource(inst, store, documented=documented if documented is not None else Mapping(MAPPING), **kw)


def load(src):
    src.set_window(DAY, DAY)
    return src.load()


class SameShapeAsMock(unittest.TestCase):
    def test_same_interface_and_record_type(self):
        for name in ("set_window", "load", "unmapped", "unmapped_notes", "warnings", "needs_window"):
            self.assertTrue(hasattr(R365ReadOnlySource, name) or name in ("unmapped", "unmapped_notes", "warnings"))
        self.assertTrue(issubclass(R365ReadOnlySource, DataSource))
        self.assertTrue(hasattr(DemoAdapter(), "load"))

    def test_records_match_the_mock_field_for_field(self):
        mock_recs = DemoAdapter().load()
        with MockR365(rows_override=rows()) as srv:
            src = make(srv)
            src.set_window(date(2026, 2, 28), DAY)
            real = src.load()
        self.assertEqual(sorted(real, key=lambda r: (r.location, r.business_date)),
                         sorted(mock_recs, key=lambda r: (r.location, r.business_date)))
        names = [f.name for f in dataclasses.fields(DayRecord)]
        self.assertEqual([f.name for f in dataclasses.fields(real[0])], names)
        for r, m in zip(real, mock_recs):
            self.assertIs(type(r), type(m))

    def test_recorded_fixture_shape(self):
        with MockR365(rows_override=FIXTURE) as srv:
            recs = {r.location: r for r in load(make(srv))}
        self.assertEqual(set(recs), {"Sample Pier Grill", "Sample Hill Bistro", "Sample Dock Cafe"})
        for r in recs.values():
            self.assertIsInstance(r, DayRecord)
            self.assertEqual(set(r.payments), {"cash", "card", "gift_card", "delivery_app"})


class MissingFieldsAreUnknown(unittest.TestCase):
    def test_fields_absent_from_the_answer_are_none_never_zero(self):
        with MockR365(rows_override=FIXTURE) as srv:
            recs = {r.location: r for r in load(make(srv))}
        hill = recs["Sample Hill Bistro"]
        for f in ("cash_over_short", "missing_receipts", "payment_exceptions", "pos_import_received"):
            self.assertIsNone(getattr(hill, f), f)
        self.assertEqual(set(hill.payments.values()), {None})
        self.assertIs(hill.approved, False)           # "Open" is a listed word in this test spec
        dock = recs["Sample Dock Cafe"]
        self.assertIsNone(dock.sales_total)
        self.assertIsNone(dock.approved)               # "Mystery" is not a listed word: UNKNOWN

    def test_shipped_table_is_all_unknown_and_fetches_nothing(self):
        documented = load_documented_fields()
        self.assertEqual(unknown_fields(documented),
                         ["entity", "location", "business_date", *documented.fields, "payments"])
        with MockR365() as srv:
            src = make(srv, documented=documented)
            self.assertEqual(load(src), [])
            self.assertEqual(srv.requests, [])         # no names known, so not even a guess is sent
        self.assertTrue(set(src.unmapped) >= set(documented.fields))
        self.assertTrue(any("UNKNOWN" in n for n in src.unmapped_notes))

    def test_gaps_doc_lists_every_unknown_item(self):
        text = (ROOT / "docs/R365_FIELD_GAPS.md").read_text()
        for item in unknown_fields(load_documented_fields()):
            self.assertIn(f"`{item}`", text, item)

    def test_module_cites_public_docs(self):
        import dssreport.r365_readonly as m
        for url in m.DOC_URLS:
            self.assertIn(url, m.__doc__)


class ReadOnly(unittest.TestCase):
    def test_http_layer_only_ever_sees_get(self):
        seen = []
        real = http.client.HTTPConnection.request

        def spy(self, method, url, *a, **k):
            seen.append(method)
            return real(self, method, url, *a, **k)

        with MockR365(rows_override=FIXTURE) as srv, mock.patch.object(http.client.HTTPConnection, "request", spy):
            src = make(srv)
            load(src)
            src.check_connection()
            src.describe()
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"GET"})
        self.assertEqual({m for m, _, _ in srv.requests}, {"GET"})

    def test_no_write_methods_and_no_write_words_in_module(self):
        for verb in ("post", "put", "patch", "delete", "send", "approve"):
            self.assertFalse(hasattr(R365ReadOnlySource, verb))
        code = re.sub(r'""".*?"""', "", (ROOT / "dssreport/r365_readonly.py").read_text(), flags=re.S)
        self.assertNotRegex(code, r"(?i)\b(POST|PUT|PATCH|DELETE)\b|approve\(")


class SwitchedBySettings(unittest.TestCase):
    def test_source_kind_selects_the_connector(self):
        inst = Instance(id="a", name="A", base_url="https://example.invalid/odata", username="D\\u",
                        source_kind="r365-readonly")
        validate(Settings(instances=[inst]))
        self.assertIsInstance(build_source(inst, InMemoryStoreForTests()), R365ReadOnlySource)


if __name__ == "__main__":
    unittest.main()
