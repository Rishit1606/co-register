"""Schedule solver: pick sections for the shared course plus a student's other classes.

Runs INSIDE one agent, on that student's private data. Backtracking over sections:
  - hard rules (busy blocks, overlaps, hard constraints, and any "strict" soft prefs)
    reject a branch immediately;
  - soft prefs that are broken cost their priority in points; cheapest schedule wins.
All rules are monotone (adding a section never un-breaks one), so pruning a partial
schedule is safe.

The group helper, shared_section_options(), only learns a yes/no per agent per
section: the same thing ACCEPT/DECLINE reveals on the bus.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from models import Constraint, Course, Preference, Section, Student, format_time


# ---- rules -----------------------------------------------------------------

def breaks(kind: str, value, sections: list[Section], credits: int) -> bool:
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


def show(rule: Constraint | Preference) -> str:
    """Human-readable rule, e.g. 'no_before 09:00'. For the student's own eyes only."""
    value = format_time(rule.value) if rule.kind in ("no_before", "no_after") else rule.value
    return f"{rule.kind} {value}"


def _credits(sections: list[Section], catalog: dict[str, Course]) -> int:
    return sum(catalog[s.course_id].credits for s in sections)


def hard_violations(student: Student, sections: list[Section], catalog: dict[str, Course]) -> list[str]:
    """Why these sections can't work for this student. Private: contains busy-block labels."""
    out = []
    for i, s in enumerate(sections):
        for m in s.meetings:
            for b in student.busy_blocks:
                if m.overlaps(b):
                    out.append(f"{s.id} {m} clashes with {b.label} ({b})")
        for other in sections[i + 1:]:
            if any(a.overlaps(b) for a in s.meetings for b in other.meetings):
                out.append(f"{s.id} overlaps {other.id}")
    credits = _credits(sections, catalog)
    for c in student.hard_constraints:
        if breaks(c.kind, c.value, sections, credits):
            out.append(f"breaks {show(c)}")
    return out


def broken_prefs(prefs, sections: list[Section], catalog: dict[str, Course]) -> list[Preference]:
    credits = _credits(sections, catalog)
    return [p for p in prefs if breaks(p.kind, p.value, sections, credits)]


# ---- one student -----------------------------------------------------------

@dataclass(frozen=True)
class Schedule:
    section_ids: tuple[str, ...]        # shared section first
    assignments: dict[str, str]         # requirement category -> section id
    cost: int                           # sum of priorities of broken soft prefs
    broken: tuple[Preference, ...]      # soft prefs this schedule breaks (relaxed ones only, if strict)


def _candidates(student: Student, catalog: dict[str, Course], requirement: str,
                exclude_course: str) -> list[Section]:
    """Sections that could fill a requirement. Full sections only if the student already holds a seat."""
    out = [
        s
        for cid in sorted(catalog)
        if requirement in catalog[cid].tags and cid != exclude_course
        for s in catalog[cid].sections
        if not s.is_full or s.id in student.holds
    ]
    # Held seats first, so on a tie the student keeps what they have.
    return sorted(out, key=lambda s: (s.id not in student.holds, s.id))


def best_schedule(student: Student, catalog: dict[str, Course], sections: dict[str, Section],
                  shared_section_id: str, counts_as: frozenset[str],
                  strict: frozenset[Preference] = frozenset()) -> Schedule | None:
    """Cheapest full schedule around a fixed shared section, or None if none exists.

    `counts_as`: which of the student's categories the shared course could fill (it fills one).
    `strict`: soft prefs to treat as hard (the agent's still-active prefs).
    """
    shared = sections[shared_section_id]
    best: Schedule | None = None
    for filled in sorted(counts_as & student.open_requirements):
        remaining = student.open_requirements - {filled}
        found = _search(student, catalog, shared, filled, remaining, strict,
                        bound=best.cost if best else math.inf)
        if found and (best is None or found.cost < best.cost):
            best = found
    return best


def _search(student, catalog, shared, filled, remaining, strict, bound) -> Schedule | None:
    cands = {r: _candidates(student, catalog, r, shared.course_id) for r in remaining}
    reqs = sorted(remaining, key=lambda r: (len(cands[r]), r))  # most constrained first
    chosen: list[Section] = [shared]
    best: Schedule | None = None
    best_cost = bound

    def invalid() -> bool:
        return bool(hard_violations(student, chosen, catalog) or broken_prefs(strict, chosen, catalog))

    def cost() -> int:
        return sum(p.priority for p in broken_prefs(student.soft_prefs, chosen, catalog))

    def go(i: int) -> None:
        nonlocal best, best_cost
        if cost() >= best_cost:
            return
        if i == len(reqs):
            best_cost = cost()
            assignments = {filled: shared.id} | {r: s.id for r, s in zip(reqs, chosen[1:])}
            best = Schedule(
                section_ids=tuple(s.id for s in chosen),
                assignments=dict(sorted(assignments.items())),
                cost=best_cost,
                broken=tuple(broken_prefs(student.soft_prefs, chosen, catalog)),
            )
            return
        used = {s.course_id for s in chosen}
        for s in cands[reqs[i]]:
            if s.course_id in used:  # one course can't fill two requirements
                continue
            chosen.append(s)
            if not invalid():
                go(i + 1)
            chosen.pop()

    if not invalid():
        go(0)
    return best


# ---- the group -------------------------------------------------------------

@dataclass(frozen=True)
class SectionOption:
    section_id: str
    fits: dict[str, bool]   # agent id -> "a schedule exists for me with this section"
    seats_short: int        # seats missing for everyone to get in

    @property
    def fits_all(self) -> bool:
        return all(self.fits.values())

    @property
    def needs_swap(self) -> bool:
        return self.seats_short > 0


def shared_section_options(agents, shared, catalog: dict[str, Course]) -> list[SectionOption]:
    """Every section of the shared course, with a yes/no from each agent.

    `agents` need .id, .plan(section_id, counts_as) and .holds(section_id).
    `shared` is a course_finder.SharedCourse. Order: fits everyone, enough seats, then id.
    """
    out = []
    for section in catalog[shared.course_id].sections:
        fits = {a.id: a.plan(section.id, shared.counts_as[a.id]) is not None for a in agents}
        need = sum(1 for a in agents if not a.holds(section.id))
        out.append(SectionOption(section.id, fits, max(0, need - section.seats_left)))
    return sorted(out, key=lambda o: (not o.fits_all, o.needs_swap, o.section_id))
