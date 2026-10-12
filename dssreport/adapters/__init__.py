"""Data sources. The product's real source is Restaurant365 (read-only, see dssreport/r365.py).
The file and demo sources exist for the demo, the tests and offline trials."""

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
    if spec == "r365":
        # imported here so file-only use never needs the credential store
        from .. import paths
        from ..credstore import default_store
        from ..r365 import Mapping, R365Adapter
        from ..settings import load_settings
        return R365Adapter(load_settings(), Mapping.load(paths.mapping_path()), default_store(),
                           include=getattr(cfg, "include", []))
    return FileAdapter(spec)


__all__ = ["Adapter", "DemoAdapter", "FileAdapter", "build_adapter"]
