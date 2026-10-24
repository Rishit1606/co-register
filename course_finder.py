"""Find courses that count for every student, even across different majors.

Works only from what agents SHARED (their open requirement categories), never from
private Student data. A course qualifies when, for every student,
course.tags & open_categories is non-empty.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import Course, Message, MessageType


@dataclass(frozen=True)
class SharedCourse:
    course_id: str
    counts_as: dict[str, frozenset[str]]  # agent id -> categories this course satisfies for them

    @property
    def total(self) -> int:
        return sum(len(c) for c in self.counts_as.values())


def categories_from_messages(messages: list[Message]) -> dict[str, set[str]]:
    """Collect each sender's shared open_categories from SHARE messages."""
    out = {}
    for m in messages:
        if m.type is MessageType.SHARE and "open_categories" in m.payload:
            out[m.sender] = set(m.payload["open_categories"])
    return out


def _coverage(course: Course, categories: dict[str, set[str]]) -> dict[str, frozenset[str]]:
    return {sid: frozenset(course.tags & cats) for sid, cats in categories.items()}


def find_shared_courses(catalog: dict[str, Course], categories: dict[str, set[str]]) -> list[SharedCourse]:
    """Courses that satisfy an open category for everyone. Most total coverage first, then by id."""
    if not categories:
        return []
    found = []
    for course in catalog.values():
        cov = _coverage(course, categories)
        if all(cov.values()):
            found.append(SharedCourse(course.id, cov))
    return sorted(found, key=lambda c: (-c.total, c.course_id))


def near_misses(catalog: dict[str, Course], categories: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Courses that work for everyone but exactly one student: (course_id, missing agent id)."""
    if len(categories) < 2:
        return []
    out = []
    for course in catalog.values():
        missing = [sid for sid, tags in _coverage(course, categories).items() if not tags]
        if len(missing) == 1:
            out.append((course.id, missing[0]))
    return sorted(out)
