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
    Course,
    Message,
    MessageType,
    Preference,
    Section,
    Student,
    format_time,
    parse_time,
)
from solver import Schedule, best_schedule, broken_prefs, hard_violations, show

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
    MessageType.RELAX: {"level"},
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

    def relax_to(self, level: int) -> list[Preference]:
        """Relax every active soft pref with priority <= level. Returns what was newly relaxed."""
        newly = [p for p in self.active_prefs() if p.priority <= level]
        self._relaxed.update(newly)
        return newly

    def reset(self) -> None:
        """Forget all relaxations: a re-plan starts from the student's full preferences."""
        self._relaxed.clear()

    def relaxed_prefs(self) -> list[Preference]:
        """The soft prefs this agent relaxed. Only for this agent's own student."""
        return [p for p in self._student.soft_prefs if p in self._relaxed]

    def relaxed(self) -> list[str]:
        """What this agent gave up, in words. Only for this agent's own student."""
        return [show(p) for p in self._student.soft_prefs if p in self._relaxed]

    def holds(self, section_id: str) -> bool:
        return section_id in self._student.holds

    def evaluate(self, section_ids: list[str]) -> Evaluation:
        """Check a set of sections against busy blocks, hard constraints and active soft prefs."""
        sections = [self._sections[sid] for sid in section_ids]
        return Evaluation(
            hard=hard_violations(self._student, sections, self._catalog),
            soft=broken_prefs(self.active_prefs(), sections, self._catalog),
        )

    def plan(self, shared_section_id: str, counts_as: frozenset[str] | None = None) -> Schedule | None:
        """Best full schedule around a shared section. Still-active soft prefs act as hard."""
        if counts_as is None:
            course = self._catalog[self._sections[shared_section_id].course_id]
            counts_as = course.tags & self._student.open_requirements
        return best_schedule(self._student, self._catalog, self._sections, shared_section_id,
                             frozenset(counts_as), strict=frozenset(self.active_prefs()))

    def tradeable_seats(self, shared_section_id: str) -> list[str]:
        """Seats I hold but won't need if I take this shared section: what I can offer in a swap."""
        plan = self.plan(shared_section_id)
        keep = set(plan.section_ids) if plan else set()
        return [sid for sid in self._student.holds if sid not in keep]

    def next_option(self, course_id: str, group_size: int, tried: set[str]) -> str | None:
        """The section of a shared course this agent would propose next, or None if it has none left.

        Cheapest for me first; among equals, sections with a seat for everyone first.
        """
        ranked = []
        for s in self._catalog[course_id].sections:
            if s.id in tried:
                continue
            sched = self.plan(s.id)
            if sched is not None:
                ranked.append((sched.cost, s.seats_left < group_size, s.id))
        return min(ranked)[2] if ranked else None

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

    def respond(self, proposal: Message) -> Message:
        """Accept iff I can build a full schedule around the proposed section. The reason stays private."""
        sid = proposal.payload["section_id"]
        type = MessageType.ACCEPT if self.plan(sid) is not None else MessageType.DECLINE
        return self._send(proposal.sender, type, {"section_id": sid}, proposal.round)

    def handle(self, msg: Message) -> Message | None:
        """React to an incoming message. Returns a reply to send, if any."""
        if msg.type in (MessageType.PROPOSE, MessageType.COUNTER):
            return self.respond(msg)
        if msg.type is MessageType.RELAX:
            self.relax_to(msg.payload["level"])
        return None

    def call_relax(self, level: int, round: int = 0) -> Message:
        """Lead the group into relaxation `level` (relaxing my own prefs too)."""
        self.relax_to(level)
        return self._send("all", MessageType.RELAX, {"level": level}, round)

    def confirm(self, section_id: str, yes: bool, round: int = 0) -> Message:
        """Tell the group my student's final answer. A "no" carries no reason."""
        type = MessageType.ACCEPT if yes else MessageType.DECLINE
        return self._send("all", type, {"section_id": section_id}, round)

    def swap_offer(self, give: str, want: str, recipient: str, round: int = 0) -> Message:
        """Offer `recipient` their part of a swap: they give `give`, they receive `want`."""
        payload = {"give_section": give, "want_section": want}
        return self._send(recipient, MessageType.SWAP_OFFER, payload, round)

    def escalate(self, section_id: str, options: list[str], round: int = 0) -> Message:
        payload = {"section_id": section_id, "options": options}
        return self._send(f"human:{self.id}", MessageType.ESCALATE_TO_HUMAN, payload, round)

