"""Small memory kept between runs (in the program's own folder): which locations have been seen,
and when the last scheduled report ran. Contains no secrets and no sales figures."""

import json
from pathlib import Path

from .paths import state_path


def load_state(path=None) -> dict:
    path = Path(path) if path else state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict, path=None) -> None:
    path = Path(path) if path else state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def known_locations(state: dict) -> list:
    v = state.get("known_locations", [])
    return [x for x in v if isinstance(x, str)]


def remember_locations(state: dict, names) -> dict:
    state["known_locations"] = sorted(set(known_locations(state)) | set(names))
    return state
