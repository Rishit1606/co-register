"""Load the mock JSON data in data/ into model objects, validating as we go."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from models import (
    DAYS,
    RULE_KINDS,
    TIME_KINDS,
    Constraint,
    Course,
    Preference,
    SeatHolder,
    Section,
    Student,
    TimeBlock,
    parse_time,
)

DATA_DIR = Path(__file__).parent / "data"


@dataclass
class Scenario:
    catalog: dict[str, Course]
    sections: dict[str, Section]  # every section by id, across all courses
    students: dict[str, Student]
    seat_holders: dict[str, SeatHolder]


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _blocks(raw: dict) -> list[TimeBlock]:
    """{"days": ["Wed", "Fri"], "start": "11:00", ...} -> one TimeBlock per day."""
    start, end = parse_time(raw["start"]), parse_time(raw["end"])
    if start >= end:
        raise ValueError(f"block ends before it starts: {raw}")
    blocks = []
    for day in raw["days"]:
        if day not in DAYS:
            raise ValueError(f"unknown day {day!r} in {raw}")
        blocks.append(TimeBlock(day, start, end, raw.get("label", "")))
    return blocks


def _rule_value(kind: str, value):
    if kind not in RULE_KINDS:
        raise ValueError(f"unknown rule kind {kind!r}")
    return parse_time(value) if kind in TIME_KINDS else value


def _unique(ids: list[str], what: str) -> None:
    seen = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {what} id {i!r}")
        seen.add(i)


def load_catalog(path: Path = DATA_DIR / "catalog.json") -> dict[str, Course]:
    raw = _read(path)["courses"]
    _unique([c["id"] for c in raw], "course")
    courses = {}
    for c in raw:
        sections = tuple(
            Section(
                id=s["id"],
                course_id=c["id"],
                meetings=tuple(b for m in s["meetings"] for b in _blocks(m)),
                seats_left=s["seats_left"],
            )
            for s in c["sections"]
        )
        courses[c["id"]] = Course(
            id=c["id"],
            title=c["title"],
            credits=c["credits"],
            tags=frozenset(c["tags"]),
            sections=sections,
        )
    _unique([s.id for c in courses.values() for s in c.sections], "section")
    return courses


def load_students(path: Path = DATA_DIR / "students.json") -> dict[str, Student]:
    raw = _read(path)["students"]
    _unique([s["id"] for s in raw], "student")
    students = {}
    for s in raw:
        students[s["id"]] = Student(
            id=s["id"],
            name=s["name"],
            major=s["major"],
            open_requirements=frozenset(s["open_requirements"]),
            busy_blocks=tuple(b for raw in s["busy_blocks"] for b in _blocks(raw)),
            hard_constraints=tuple(
                Constraint(r["kind"], _rule_value(r["kind"], r["value"]))
                for r in s["hard_constraints"]
            ),
            soft_prefs=tuple(
                Preference(r["kind"], _rule_value(r["kind"], r["value"]), r["priority"])
                for r in s["soft_prefs"]
            ),
            holds=tuple(s["holds"]),
            gpa=s["private"]["gpa"],
            transcript=tuple(s["private"]["transcript"]),
        )
    return students


def load_seat_holders(path: Path = DATA_DIR / "seat_holders.json") -> dict[str, SeatHolder]:
    raw = _read(path)["seat_holders"]
    _unique([h["id"] for h in raw], "seat holder")
    return {
        h["id"]: SeatHolder(h["id"], h["name"], h["holds"], tuple(h["would_accept"]))
        for h in raw
    }


def load_scenario(data_dir: Path = DATA_DIR) -> Scenario:
    """Load everything and check that every section reference points somewhere real."""
    catalog = load_catalog(data_dir / "catalog.json")
    sections = {s.id: s for c in catalog.values() for s in c.sections}
    students = load_students(data_dir / "students.json")
    holders = load_seat_holders(data_dir / "seat_holders.json")

    def check(section_id: str, owner: str) -> None:
        if section_id not in sections:
            raise ValueError(f"{owner} refers to unknown section {section_id!r}")

    for st in students.values():
        for sid in st.holds:
            check(sid, f"student {st.id}")
    for h in holders.values():
        check(h.holds, f"seat holder {h.id}")
        for sid in h.would_accept:
            check(sid, f"seat holder {h.id}")
    if set(students) & set(holders):
        raise ValueError("a seat holder id collides with a student id")

    return Scenario(catalog, sections, students, holders)
