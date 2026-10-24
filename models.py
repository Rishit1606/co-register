"""Core data shapes for Co-Register.

Plain dataclasses with no business logic. Times are stored as minutes since
midnight (8:00 -> 480) so comparisons are simple integer math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")

# Kinds of rules a student can have. The same kind can be hard or soft
# depending on the student; e.g. Maya's "no_after" is hard, Ana's "no_before" is soft.
TIME_KINDS = {"no_before", "no_after"}  # value is minutes since midnight
DAY_KINDS = {"day_off"}                 # value is a day name, e.g. "Fri"
COUNT_KINDS = {"max_days", "max_credits"}  # value is an int
RULE_KINDS = TIME_KINDS | DAY_KINDS | COUNT_KINDS


def parse_time(text: str) -> int:
    """'14:30' -> 870."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def format_time(minutes: int) -> str:
    """870 -> '14:30'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class TimeBlock:
    """One meeting on one day, e.g. Wed 11:00-12:15.

    `label` is free text ("Lecture", "Work: campus bookstore"). For a student's
    busy blocks the label is private and must never leave the agent.
    """

    day: str
    start: int
    end: int
    label: str = ""

    def overlaps(self, other: TimeBlock) -> bool:
        return self.day == other.day and self.start < other.end and other.start < self.end

    def __str__(self) -> str:
        return f"{self.day} {format_time(self.start)}-{format_time(self.end)}"


@dataclass(frozen=True)
class Section:
    id: str
    course_id: str
    meetings: tuple[TimeBlock, ...]
    seats_left: int

    @property
    def is_full(self) -> bool:
        return self.seats_left <= 0

    @property
    def days(self) -> set[str]:
        return {m.day for m in self.meetings}


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    credits: int
    tags: frozenset[str]  # requirement categories this course satisfies
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Constraint:
    """A HARD rule: a schedule that breaks it is rejected outright."""

    kind: str
    value: int | str


@dataclass(frozen=True)
class Preference:
    """A SOFT rule: breaking it costs points. Lower priority is relaxed first."""

    kind: str
    value: int | str
    priority: int


@dataclass
class Student:
    id: str
    name: str
    major: str
    open_requirements: frozenset[str]
    busy_blocks: tuple[TimeBlock, ...]
    hard_constraints: tuple[Constraint, ...]
    soft_prefs: tuple[Preference, ...]
    holds: tuple[str, ...]  # section ids this student is already enrolled in
    # Private: exist so the share-policy test has something real to protect.
    gpa: float
    transcript: tuple[str, ...]


@dataclass(frozen=True)
class SeatHolder:
    """A mock student outside the friend group who holds a seat and might trade it."""

    id: str
    name: str
    holds: str                      # section id they hold
    would_accept: tuple[str, ...]   # section ids they would trade for


class MessageType(Enum):
    SHARE = "SHARE"  # informational: open categories, free windows
    PROPOSE = "PROPOSE"
    COUNTER = "COUNTER"
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    SWAP_OFFER = "SWAP_OFFER"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    RELAX = "RELAX"  # "everyone relax soft prefs up to this level"; who relaxed what stays private


@dataclass(frozen=True)
class Message:
    """What one agent sends another. Only `payload` carries content."""

    sender: str
    recipient: str  # an agent id, or "all"
    type: MessageType
    payload: dict = field(default_factory=dict)
    round: int = 0

    def field_names(self) -> list[str]:
        """Payload keys, logged so the demo can prove what was shared."""
        return sorted(self.payload)
