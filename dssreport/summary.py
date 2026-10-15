"""Optional one-sentence summary from a LOCAL model (Ollama-compatible endpoint).

Off by default. The report never depends on it. The model's sentence is only
used if it passes `sentence_agrees()`; otherwise the standard sentence is used.
"""

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .config import Config
from .report import Report, date_label

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BANNED = ["all clean", "all clear", "all good", "no issues", "no exceptions", "no problems",
          "everything is fine", "nothing needs", "no location", "no locations"]


def standard_sentence(report: Report) -> str:
    """Plain template sentence built straight from the computed facts."""
    if report.total == 0:
        return "No locations were found in the data, so nothing could be checked (UNKNOWN)."
    label = date_label(report.dates)
    if not report.attention:
        return f"All {report.total} locations were checked for {label} and none has anything to review."
    names = ", ".join(r.name for r in report.attention)
    text = f"{len(report.attention)} of {report.total} locations need a look for {label}: {names}."
    if report.unknown_only:
        text += f" {report.unknown_only} of them could not be fully checked because data is missing (UNKNOWN)."
    return text


def _facts_prompt(report: Report) -> str:
    return (
        "Write ONE plain-English sentence summarising this morning review for an accounting "
        "reviewer. Use digits for numbers. Name every location that needs a look. Do not name "
        "any other location. Do not add any number that is not given. Do not say anything is "
        "clean or fine if a location is listed as needing a look. If some locations are UNKNOWN "
        "(data missing), say data is missing.\n"
        f"Period: {date_label(report.dates)}\n"
        f"Locations checked: {report.total}\n"
        f"Locations needing a look: {len(report.attention)} "
        f"({', '.join(r.name for r in report.attention) or 'none'})\n"
        f"Of those, UNKNOWN because data is missing: {report.unknown_only}\n"
        f"Locations with nothing to review: {len(report.clear)}\n"
        "Reply with the sentence only."
    )


def sentence_agrees(sentence: str, report: Report) -> bool:
    """True only if the sentence is consistent with the computed facts."""
    s = sentence.strip().strip('"').strip()
    if not s or "\n" in s or len(s) > 350:
        return False
    low = s.lower()
    if report.attention and any(b in low for b in BANNED):
        return False
    allowed = {report.total, len(report.attention), len(report.clear), report.unknown_only,
               len(report.dates)}
    for d in report.dates:
        allowed.update({d.year, d.month, d.day})
    numbers = [int(x) for x in re.findall(r"\d+", s)]
    if any(n not in allowed for n in numbers):
        return False
    if report.attention:
        if len(report.attention) not in numbers:
            return False
        if not all(r.name.lower() in low for r in report.attention):
            return False
    elif report.total not in numbers:
        return False
    if any(r.name.lower() in low for r in report.clear):
        return False
    if report.unknown_only and not any(w in low for w in ("unknown", "missing", "no data")):
        return False
    return True


def _is_local(endpoint: str) -> bool:
    try:
        host = urlparse(endpoint).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def ask_model(prompt: str, cfg: Config) -> str:
    """POST to the local endpoint. Raises on any problem; the caller falls back."""
    if not _is_local(cfg.ai_endpoint):
        raise ValueError("the model endpoint must be on this computer (localhost)")
    body = json.dumps({"model": cfg.ai_model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(cfg.ai_endpoint.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=cfg.ai_timeout) as resp:
        return json.loads(resp.read().decode())["response"]


def add_summary(report: Report, cfg: Config, ask=ask_model, failed: int = 0) -> str:
    """Fill report.summary_sentence. Returns a note for the console (empty if all went well)."""
    note = ""
    if failed:
        # a connection that could not be reached means the facts are incomplete: never let a model
        # sentence imply otherwise, use the plain template
        report.summary_sentence = (standard_sentence(report) + f" {failed} connection"
                                   f"{' was' if failed == 1 else 's were'} not reached (UNKNOWN).")
        report.summary_source = "template"
        return ""
    try:
        sentence = ask(_facts_prompt(report), cfg).strip().strip('"').strip()
        if sentence_agrees(sentence, report):
            report.summary_sentence, report.summary_source = sentence, "model"
            return ""
        note = "The local model's sentence did not match the computed facts, so it was discarded."
    except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
        note = f"The local model could not be used ({exc}); the standard sentence was used."
    report.summary_sentence, report.summary_source = standard_sentence(report), "template"
    return note
