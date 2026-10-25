"""Wording only. Turns facts into readable sentences; never decides anything.

Templates are the default and always work offline. With an LLM enabled (Gemini free
tier, key in .env), Phraser.polish() may reword a PUBLIC summary line, but the result
is thrown away unless it keeps every course code, section id, name and number from
the template. Private briefings are never sent to the LLM.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from models import Preference, Section, format_time

DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}


# ---- facts -> words --------------------------------------------------------

def clock(minutes: int) -> str:
    """540 -> '9:00 AM'."""
    h, m = divmod(minutes, 60)
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def describe_pref(p: Preference) -> str:
    if p.kind == "no_before":
        return f"no classes before {clock(p.value)}"
    if p.kind == "no_after":
        return f"nothing after {clock(p.value)}"
    if p.kind == "day_off":
        return f"{DAY_NAMES[p.value]}s off"
    if p.kind == "max_days":
        return f"classes on at most {p.value} days"
    if p.kind == "max_credits":
        return f"at most {p.value} credits"
    return f"{p.kind} {p.value}"


def when(section: Section) -> str:
    """'Wed/Fri 11:00-12:15' (meetings with the same time grouped)."""
    groups: dict[tuple, list[str]] = {}
    for m in section.meetings:
        groups.setdefault((m.start, m.end, m.label), []).append(m.day)
    parts = []
    for (start, end, label), days in groups.items():
        lab = f" {label.lower()}" if label and label != "Lecture" else ""
        parts.append(f"{'/'.join(days)} {format_time(start)}-{format_time(end)}{lab}")
    return ", ".join(parts)


def join_names(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def trade(t, names: dict[str, str], viewer: str | None = None) -> str:
    """'Priya gives a PHIL215-04 seat to you' (viewer = whose briefing this is)."""
    giver = "You give your" if t.giver == viewer else f"{names.get(t.giver, t.giver)} gives a"
    receiver = "you" if t.receiver == viewer else names.get(t.receiver, t.receiver)
    return f"{giver} {t.section_id} seat to {receiver}"


def narrate(entry, names: dict[str, str], sections: dict[str, Section]) -> str | None:
    """One readable line for a bus LogEntry. Uses only what the message itself carried."""
    who = names.get(entry.sender, entry.sender)
    agent = f"{who}'s agent"
    p = entry.payload
    sec = p.get("section_id")
    at = f"{sec} ({when(sections[sec])})" if sec in sections else str(sec)

    if entry.type == "SHARE" and "open_categories" in p:
        return f"{agent} shares the requirement categories {who} still needs: {', '.join(p['open_categories'])}"
    if entry.type == "SHARE" and "free_windows" in p:
        return f"{agent} shares {len(p['free_windows'])} free time windows (no reasons attached)"
    if entry.type == "PROPOSE":
        return f"[round {entry.round}] {agent} proposes {at}"
    if entry.type == "COUNTER":
        return f"[round {entry.round}] {agent} counters with {at}"
    if entry.type == "RELAX":
        return (f"[round {entry.round}] Nobody has a section left that works for everyone. {agent} calls "
                f"relaxation level {p['level']}: each agent may privately drop its least important "
                f"preferences. Nobody says which. Agents re-check the sections they declined.")
    if entry.type == "SWAP_OFFER":
        to = names.get(entry.recipient, entry.recipient)
        return f"{agent} offers {to} a trade: give {p['give_section']}, get {p['want_section']}"
    if entry.type == "ESCALATE_TO_HUMAN":
        return f"{agent} escalates to {who}: no section works for everyone"
    if entry.type in ("ACCEPT", "DECLINE") and entry.recipient == "all":
        return (f"✔ {who} confirmed {sec}" if entry.type == "ACCEPT"
                else f"✘ {who} said no to {sec} (no reason shared)")
    if entry.type == "ACCEPT":
        return f"    {agent}: accepts {sec}"
    if entry.type == "DECLINE":
        return f"    {agent}: declines {sec} (no reason shared)"
    return None


# ---- optional LLM polish ---------------------------------------------------

FACT = re.compile(r"[A-Z]{2,5}\d{3}(?:-\d{2})?|\d+(?::\d{2})?")


def _facts(text: str, keep: tuple[str, ...] = ()) -> set[str]:
    """Course codes, section ids, numbers, plus any of `keep` (e.g. names) found in text."""
    return set(FACT.findall(text)) | {k for k in keep if k in text}


class Phraser:
    """Template wording, optionally reworded by an LLM that must keep every fact."""

    def __init__(self, generate: Callable[[str], str] | None = None):
        self._generate = generate
        self._cache: dict[str, str] = {}

    @property
    def uses_llm(self) -> bool:
        return self._generate is not None

    def polish(self, text: str, keep: tuple[str, ...] = ()) -> str:
        """Maybe reword `text`. Every code, number and `keep` word must survive, or the template wins."""
        if self._generate is None:
            return text
        if text not in self._cache:
            self._cache[text] = self._try(text, tuple(keep))
        return self._cache[text]

    def _try(self, text: str, keep: tuple[str, ...]) -> str:
        prompt = ("Rewrite this status line from a class-scheduling demo as one clear, friendly "
                  "sentence. Keep every name, course code, section id and number exactly as written. "
                  "Do not add any facts.\n\n" + text)
        try:
            out = (self._generate(prompt) or "").strip()
        except Exception:
            return text
        if not out or "\n" in out or not _facts(text, keep) <= _facts(out, keep):
            return text  # the LLM dropped or changed a fact: keep the template
        return out

    @classmethod
    def from_env(cls, use_llm: bool) -> Phraser:
        """Gemini if asked for AND a key is set AND google-genai is installed; else templates."""
        if not use_llm:
            return cls()
        _load_dotenv()
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            return cls()
        try:
            from google import genai
        except ImportError:
            return cls()
        client = genai.Client(api_key=key)
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        return cls(lambda prompt: client.models.generate_content(model=model, contents=prompt).text)


def _load_dotenv(path: Path = Path(__file__).parent / ".env") -> None:
    """Minimal .env reader (KEY=value lines). Never prints anything."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
