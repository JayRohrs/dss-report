"""Demo and trial-file sources. The live Restaurant365 sources are in dssreport/sources.py and r365.py."""

from ..errors import InputError
from .base import Adapter
from .demo import DemoAdapter
from .files import FileAdapter


def build_adapter(spec: str, cfg=None) -> Adapter:
    """Pick an adapter from the --input value.

    """
    if not spec:
        raise InputError("No input given. Use --input demo, or a .csv/.json file or folder.")
    if spec == "demo":
        return DemoAdapter()
    return FileAdapter(spec)


__all__ = ["Adapter", "DemoAdapter", "FileAdapter", "build_adapter"]
