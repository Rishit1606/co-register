"""An Agent acts for one student: it holds their private data and shares only what the policy allows.

Every outgoing message goes through Agent._send(), which runs SharePolicy.check()
first. Reasoning methods (evaluate, free_windows) are private to the agent and to
its own student; only their *conclusions* (accept/decline, unlabeled windows) leave.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from models import (
    DAYS,
    RULE_KINDS,
    Constraint,
    Course,
    Message,
    MessageType,
    Preference,
    Section,
    Student,
    format_time,
    parse_time,
)

CAMPUS_DAY = (parse_time("08:00"), parse_time("21:00"))

# Payload fields each message type may carry. Anything else is rejected.
ALLOWED_FIELDS: dict[MessageType, set[str]] = {
    MessageType.SHARE: {"open_categories", "free_windows"},
    MessageType.PROPOSE: {"section_id", "course_id"},
    MessageType.COUNTER: {"section_id", "course_id"},
    MessageType.ACCEPT: {"section_id"},
    MessageType.DECLINE: {"section_id"},
    MessageType.SWAP_OFFER: {"give_section", "want_section"},
    MessageType.ESCALATE_TO_HUMAN: {"section_id", "options"},
}

# Words that would reveal how a student's rules are structured (hard vs soft, priorities).
FORBIDDEN_TERMS = {"soft", "hard", "priority", "reason", "gpa", "transcript"} | RULE_KINDS


class PolicyViolation(Exception):
    pass


class SharePolicy:
    """Two checks: a field whitelist per message type, and a scan for this student's private values."""

    def __init__(self, private_values: list[str]):
        self._private = [v.lower() for v in private_values if v]

    @classmethod
    def for_student(cls, student: Student) -> SharePolicy:
        values = [str(student.gpa), *student.transcript, *(b.label for b in student.busy_blocks)]
        return cls(values)

    def check(self, type: MessageType, payload: dict) -> None:
        extra = set(payload) - ALLOWED_FIELDS[type]
        if extra:
            raise PolicyViolation(f"{type.value} may not carry field(s) {sorted(extra)}")
        text = json.dumps(payload).lower()
        for value in self._private:
            if value in text:
                raise PolicyViolation(f"{type.value} payload contains private data")
        for term in FORBIDDEN_TERMS:
            if term in text:
                raise PolicyViolation(f"{type.value} payload contains forbidden term {term!r}")


@dataclass
class Evaluation:
    """Private verdict on a set of sections. Shown to the agent's own student, never sent to others."""

    hard: list[str] = field(default_factory=list)          # human-readable hard violations
    soft: list[Preference] = field(default_factory=list)   # active soft prefs broken

    @property
    def ok(self) -> bool:
        return not self.hard and not self.soft


def _breaks(kind: str, value, sections: list[Section], credits: int) -> bool:
    meetings = [m for s in sections for m in s.meetings]
    days = {m.day for m in meetings}
    if kind == "no_before":
        return any(m.start < value for m in meetings)
    if kind == "no_after":
        return any(m.end > value for m in meetings)
    if kind == "day_off":
        return value in days
    if kind == "max_days":
        return len(days) > value
    if kind == "max_credits":
        return credits > value
    raise ValueError(f"unknown rule kind {kind!r}")


def _subtract(windows: list[tuple[int, int]], start: int, end: int) -> list[tuple[int, int]]:
    """Remove [start, end) from each window, keeping what's left on either side."""
    out = []
    for ws, we in windows:
        if end <= ws or start >= we:
            out.append((ws, we))
            continue
        if ws < start:
            out.append((ws, start))
        if end < we:
            out.append((end, we))
    return out


class Agent:
    def __init__(self, student: Student, catalog: dict[str, Course], sections: dict[str, Section]):
        self._student = student
        self._catalog = catalog
        self._sections = sections
        self._relaxed: set[Preference] = set()
        self._policy = SharePolicy.for_student(student)

    @property
    def id(self) -> str:
        return self._student.id

    @property
    def name(self) -> str:
        return self._student.name

    # ---- private reasoning -------------------------------------------------

    def active_prefs(self) -> list[Preference]:
        return [p for p in self._student.soft_prefs if p not in self._relaxed]

    def relax(self, pref: Preference) -> None:
        self._relaxed.add(pref)

    def evaluate(self, section_ids: list[str]) -> Evaluation:
        """Check a set of sections against busy blocks, hard constraints and active soft prefs."""
        sections = [self._sections[sid] for sid in section_ids]
        credits = sum(self._catalog[s.course_id].credits for s in sections)
        result = Evaluation()
        for s in sections:
            for m in s.meetings:
                for b in self._student.busy_blocks:
                    if m.overlaps(b):
                        result.hard.append(f"{s.id} {m} clashes with {b.label} ({b})")
        for c in self._student.hard_constraints:
            if _breaks(c.kind, c.value, sections, credits):
                result.hard.append(f"breaks {c.kind}={_show(c)}")
        result.soft = [p for p in self.active_prefs() if _breaks(p.kind, p.value, sections, credits)]
        return result

    def free_windows(self) -> list[dict]:
        """Unlabeled free time. Busy blocks, hard limits and active soft limits look identical."""
        rules = [*self._student.hard_constraints, *self.active_prefs()]
        out = []
        for day in DAYS:
            if any(r.kind == "day_off" and r.value == day for r in rules):
                continue
            start, end = CAMPUS_DAY
            for r in rules:
                if r.kind == "no_before":
                    start = max(start, r.value)
                elif r.kind == "no_after":
                    end = min(end, r.value)
            windows = [(start, end)] if start < end else []
            for b in self._student.busy_blocks:
                if b.day == day:
                    windows = _subtract(windows, b.start, b.end)
            out += [{"day": day, "start": format_time(s), "end": format_time(e)} for s, e in windows]
        return out

    # ---- outgoing messages (all through the policy) ------------------------

    def _send(self, recipient: str, type: MessageType, payload: dict, round: int = 0) -> Message:
        self._policy.check(type, payload)
        return Message(self.id, recipient, type, payload, round)

    def share_open_categories(self, recipient: str = "all", round: int = 0) -> Message:
        cats = sorted(self._student.open_requirements)
        return self._send(recipient, MessageType.SHARE, {"open_categories": cats}, round)

    def share_free_windows(self, recipient: str = "all", round: int = 0) -> Message:
        return self._send(recipient, MessageType.SHARE, {"free_windows": self.free_windows()}, round)

    def propose(self, section_id: str, recipient: str = "all", round: int = 0,
                counter: bool = False) -> Message:
        type = MessageType.COUNTER if counter else MessageType.PROPOSE
        payload = {"section_id": section_id, "course_id": self._sections[section_id].course_id}
        return self._send(recipient, type, payload, round)

    def respond(self, proposal: Message, other_sections: list[str] = ()) -> Message:
        """Accept or decline a proposed section. The reason stays private."""
        sid = proposal.payload["section_id"]
        verdict = self.evaluate([sid, *other_sections])
        type = MessageType.ACCEPT if verdict.ok else MessageType.DECLINE
        return self._send(proposal.sender, type, {"section_id": sid}, proposal.round)

    def swap_offer(self, give: str, want: str, recipient: str, round: int = 0) -> Message:
        payload = {"give_section": give, "want_section": want}
        return self._send(recipient, MessageType.SWAP_OFFER, payload, round)

    def escalate(self, section_id: str, options: list[str], round: int = 0) -> Message:
        payload = {"section_id": section_id, "options": options}
        return self._send(self.id, MessageType.ESCALATE_TO_HUMAN, payload, round)


def _show(rule: Constraint | Preference) -> str:
    return format_time(rule.value) if rule.kind in ("no_before", "no_after") else str(rule.value)
