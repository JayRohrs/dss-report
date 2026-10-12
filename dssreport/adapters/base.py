"""The adapter interface. See docs/ADAPTERS.md."""

from abc import ABC, abstractmethod
from typing import List, Set

from ..model import DayRecord


class Adapter(ABC):
    """A data source. Turns "wherever the numbers live" into DayRecord objects.

    Rules for adapters:
      * Return a blank/unknown value as None. Never invent a 0 or False.
      * If a row cannot be understood, raise dssreport.errors.InputError with a
        message that says which row and what is wrong. Do not skip it quietly.
      * Do not return two records for the same location and date.
      * Only read. An adapter never writes to the source system.
    """

    #: short name shown in the report footer
    name = "adapter"

    def __init__(self):
        #: plain-words notes for the person running the report (for example
        #: "column 'cash_ovr_short' was not recognised"). The command prints them.
        self.warnings: List[str] = []
        #: DayRecord field names this source cannot provide at all (not mapped yet).
        #: Rules that need them are skipped and shown as "needs mapping" - they do
        #: NOT produce a per-day UNKNOWN for every row.
        self.unmapped: Set[str] = set()
        #: shown to the person: why each unmapped field is unmapped
        self.unmapped_notes: List[str] = []

    @abstractmethod
    def load(self) -> List[DayRecord]:
        """Return every record available from this source."""
