"""Negotiation: agents take turns proposing a shared section until everyone accepts.

Each turn the next agent proposes its own best untried section (PROPOSE, then
COUNTER); the others ACCEPT or DECLINE with no reason. When every agent has run out
of sections to propose, the lead agent broadcasts RELAX {level}: every agent
privately relaxes its soft prefs with priority <= level (shared scale 1..MAX_LEVEL),
so the lowest-priority prefs go first without anyone revealing priorities. If even
MAX_LEVEL doesn't produce agreement, every agent escalates to its own human.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from agent import Agent
from bus import MessageBus
from course_finder import SharedCourse
from models import MessageType, Section

MAX_LEVEL = 3


@dataclass
class Outcome:
    status: str                    # "agreed" | "escalated" | "no_shared_course"
    course_id: str | None = None
    section_id: str | None = None
    level: int = 0                 # relaxation level reached
    seats_short: int = 0           # > 0 means a swap is needed
    rounds: int = 0
    # Private, per student: what their own agent relaxed. Shown only to that student.
    relaxed: dict[str, list[str]] = field(default_factory=dict)

    @property
    def needs_swap(self) -> bool:
        return self.seats_short > 0


def _deliver(agents: list[Agent], bus: MessageBus, skip: str) -> None:
    """Let every agent except `skip` handle its inbox and send any replies."""
    for a in agents:
        if a.id == skip:
            continue
        for msg in bus.receive(a.id):
            reply = a.handle(msg)
            if reply is not None:
                bus.send(reply)


def negotiate(agents: list[Agent], bus: MessageBus, shared_courses: list[SharedCourse],
              sections: dict[str, Section], excluded: frozenset[str] = frozenset(),
              max_level: int = MAX_LEVEL) -> Outcome:
    """Agree on one shared section. `excluded`: sections a student already said no to."""
    if not shared_courses:
        return Outcome("no_shared_course")
    for a in agents:
        bus.receive(a.id)  # start from empty inboxes

    n = len(agents)
    turn = rnd = 0
    accepts: Counter[str] = Counter()  # public tally: how many said yes to each section

    def relaxed() -> dict[str, list[str]]:
        return {a.id: a.relaxed() for a in agents if a.relaxed()}

    for level in range(max_level + 1):
        if level > 0:
            rnd += 1
            lead = agents[turn % n]
            bus.send(lead.call_relax(level, round=rnd))
            _deliver(agents, bus, skip=lead.id)

        for course in shared_courses:
            tried = set(excluded)
            passes = 0
            first = True
            while passes < n:
                proposer = agents[turn % n]
                turn += 1
                sid = proposer.next_option(course.course_id, n, tried)
                if sid is None:
                    passes += 1
                    continue
                passes = 0
                tried.add(sid)
                rnd += 1
                bus.send(proposer.propose(sid, round=rnd, counter=not first))
                first = False
                _deliver(agents, bus, skip=proposer.id)
                yes = [m for m in bus.receive(proposer.id)
                       if m.type is MessageType.ACCEPT and m.payload["section_id"] == sid]
                accepts[sid] = len(yes) + 1  # the proposer counts as a yes
                if len(yes) == n - 1:
                    need = sum(1 for a in agents if not a.holds(sid))
                    return Outcome("agreed", course.course_id, sid, level,
                                   max(0, need - sections[sid].seats_left), rnd, relaxed())

    # Still stuck: hand it to the humans, best-supported sections first.
    options = sorted(accepts, key=lambda s: (-accepts[s], s))
    best = options[0] if options else None
    rnd += 1
    for a in agents:
        bus.send(a.escalate(best, options, round=rnd))
    course_id = sections[best].course_id if best else shared_courses[0].course_id
    return Outcome("escalated", course_id, best, max_level, 0, rnd, relaxed())
