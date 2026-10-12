"""Data-source adapters. To add one, see docs/ADAPTERS.md."""

from ..errors import InputError
from .base import Adapter
from .demo import DemoAdapter
from .files import FileAdapter


def build_adapter(spec: str) -> Adapter:
    """Pick an adapter from the --input value.

    To register your own adapter, import it here and return it for a keyword
    of your choice (see the `demo` line below).
    """
    if not spec:
        raise InputError("No input given. Use --input demo, or a .csv/.json file or folder.")
    if spec == "demo":
        return DemoAdapter()
    return FileAdapter(spec)


__all__ = ["Adapter", "DemoAdapter", "FileAdapter", "build_adapter"]
