from datetime import date
from decimal import Decimal

from dssreport.adapters.demo import PLANTED, generate
from dssreport.config import Config
from dssreport.report import build_report

CFG = Config()


def demo_report(day, days=1, cfg=CFG):
    return build_report(generate(), cfg, end=day, days=days)


def planted(name):
    return PLANTED[name]


def result(report, location):
    for r in report.attention + report.clear:
        if r.name == location:
            return r
    raise KeyError(location)


def rules_fired(report, location):
    return {f.rule for f in result(report, location).findings}


def rec(**kw):
    from dssreport.model import DayRecord
    base = dict(location="Test Place", business_date=date(2026, 1, 5),
                sales_total=Decimal("1000.00"), payments={"cash": Decimal("1000.00")},
                cash_over_short=Decimal("0"), missing_receipts=0, payment_exceptions=0,
                approved=True, pos_import_received=True)
    base.update(kw)
    return DayRecord(**base)
