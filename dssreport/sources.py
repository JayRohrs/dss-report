"""The ONE interface between this program and wherever Restaurant365 data comes from.

Everything else (the rules, the report, the email, the settings screen, the schedule) talks to a
`DataSource` and nothing else. Today the only real source is the OData connector (`r365.py`). When R365
changes its API, a new connector is written as another `DataSource`, registered with `register_source`,
and an instance is switched to it - without touching the rules, report, email or settings.
Documented in docs/DATA_SOURCES.md. No new API connector is built here and none of its details are guessed.
"""

from abc import abstractmethod
from typing import Dict, FrozenSet, List, Optional, Type

from .adapters.base import Adapter
from .credstore import CredentialStore
from .errors import ConfigError, InputError
from .settings import Instance

#: Version of the mapping file format that this connector reads. A mapping file carries `version = N`;
#: a connector lists the versions it understands in `mapping_formats`.
CURRENT_MAPPING_VERSION = 1


class DataSource(Adapter):
    """A read-only source of daily sales summary records for ONE R365 instance.

    Inherited from Adapter (see adapters/base.py):
      * needs_window / set_window(start, end)  - the dates to fetch (always True here)
      * load() -> List[DayRecord]              - the records; blank/unavailable values are None, never 0/False
      * unmapped: Set[str]                     - DayRecord fields this source cannot provide at all, so the
                                                 matching checks show "needs mapping" instead of guessing
      * unmapped_notes, warnings               - plain-words notes for the person

    Added here:
      * kind                                   - the name stored in settings (`Instance.source_kind`)
      * mapping_formats                        - mapping-file versions this connector understands
      * check_connection() -> str              - prove the sign-in works; a plain sentence, or InputError
      * describe() -> List[str]                - list what the instance offers, to help fill in the mapping

    Rules every source must keep: read-only; credentials only from the credential store, never logged or
    included in an error message; any problem is an InputError/ConfigError with a plain message.
    """

    kind = ""
    mapping_formats: FrozenSet[int] = frozenset({CURRENT_MAPPING_VERSION})
    needs_window = True

    def __init__(self, instance: Instance, store: CredentialStore, include=()):
        super().__init__()
        self.instance, self.store, self.include = instance, store, list(include)

    @abstractmethod
    def check_connection(self) -> str: ...

    @abstractmethod
    def describe(self) -> List[str]: ...


SOURCE_KINDS: Dict[str, Type[DataSource]] = {}


def register_source(cls: Type[DataSource]) -> Type[DataSource]:
    if not cls.kind:
        raise ValueError("a data source needs a `kind`")
    SOURCE_KINDS[cls.kind] = cls
    return cls


def build_source(instance: Instance, store: CredentialStore, include=()) -> DataSource:
    """Make the right connector for an instance. Raises a plain-words DssError if it can't."""
    from . import r365  # noqa: F401  (registers the OData connector)
    cls = SOURCE_KINDS.get(instance.source_kind)
    if cls is None:
        raise ConfigError(f"This program has no data source called '{instance.source_kind}'.")
    return cls(instance, store, include)


def check_mapping_format(version: Optional[int], cls: Type[DataSource], where: str) -> None:
    if version not in cls.mapping_formats:
        wanted = ", ".join(str(v) for v in sorted(cls.mapping_formats))
        raise ConfigError(f"The mapping file {where} is format {version}, but this connector reads format "
                          f"{wanted}. Use a mapping file in the right format.")
