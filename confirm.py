"""Human confirmation: nothing is final until every student says yes.

Loop: share -> find shared course -> negotiate -> secure seats -> ask each student.
Each student sees a PRIVATE briefing (their own schedule, their own relaxations).
A "yes" goes on the bus as ACCEPT, a "no" as DECLINE with no reason. One "no"
excludes that section, resets relaxations, and re-plans. Stops when everyone
confirms, or when the agents have to escalate.

Try it:  python3 confirm.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent import Agent
from bus import MessageBus, human
from course_finder import categories_from_messages, find_shared_courses, near_misses
from loader import Scenario, load_scenario
from negotiation import negotiate
from phrasing import Phraser, describe_pref, join_names, trade, when
from solver import Schedule
from swaps import SeatPlan, secure_seats


@dataclass
class FinalPlan:
    status: str                                   # "confirmed" | "escalated" | "no_shared_course"
    section_id: str | None = None
    schedules: dict[str, Schedule] = field(default_factory=dict)
    seats: SeatPlan | None = None
    relaxed: dict[str, list[str]] = field(default_factory=dict)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (section, who said no / "no seat")


def names_of(sc: Scenario) -> dict[str, str]:
    return {**{h.id: h.name for h in sc.seat_holders.values()},
            **{s.id: s.name for s in sc.students.values()}}


def briefing(agent: Agent, sc: Scenario, section_id: str, seats: SeatPlan) -> str:
    """What an agent tells its OWN student. Never sent to anyone else (or to the LLM)."""
    names = names_of(sc)
    sched = agent.plan(section_id)
    course = sc.catalog[sc.sections[section_id].course_id]
    lines = [
        f"--- Private to {agent.name} ---",
        f"Shared class with your friends: {course.id} {course.title}, section {section_id} "
        f"({when(sc.sections[section_id])})",
        "Your full schedule:",
    ]
    for req, sid in sched.assignments.items():
        c = sc.catalog[sc.sections[sid].course_id]
        lines.append(f"  {req:<12} {sid:<11} {c.title:<40} {when(sc.sections[sid])}")
    if agent.id in seats.swaps:
        cycle = seats.swaps[agent.id]
        lines.append(f"The section was full, so your seat comes from a {cycle.size}-way swap "
                     "(the other students already agreed):")
        lines += [f"  {trade(t, names, viewer=agent.id)}" for t in cycle.trades]
    elif agent.id in seats.open_seats:
        lines.append("A seat is open for you.")
    relaxed = [describe_pref(p) for p in agent.relaxed_prefs()]
    if relaxed:
        lines.append(f"To make this work, your agent relaxed: {', '.join(relaxed)}. "
                     "Your friends were not told what.")
    else:
        lines.append("None of your preferences had to be relaxed.")
    return "\n".join(lines)


def ask_yes_no(prompt: str, ask: Callable[[str], str]) -> bool:
    while True:
        answer = ask(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def plan_and_confirm(sc: Scenario, bus: MessageBus | None = None,
                     ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
                     phraser: Phraser | None = None, max_attempts: int = 6) -> FinalPlan:
    bus = bus or MessageBus()
    phraser = phraser or Phraser()
    names = names_of(sc)
    keep = tuple(names.values())
    agents = [Agent(st, sc.catalog, sc.sections) for st in sc.students.values()]
    for a in agents:
        bus.register(a.id)
    shares = [a.share_open_categories() for a in agents]
    for a, m in zip(agents, shares):
        bus.send(m)
        bus.send(a.share_free_windows())

    categories = categories_from_messages(shares)
    shared = find_shared_courses(sc.catalog, categories)
    for c in shared:
        uses = ", ".join(f"{names[aid]} as {'/'.join(sorted(cats))}" for aid, cats in c.counts_as.items())
        say(phraser.polish(f"{c.course_id} {sc.catalog[c.course_id].title} counts for everyone: {uses}.", keep))
    misses = near_misses(sc.catalog, categories)
    if misses:
        say("Also considered, but each misses one friend: "
            + ", ".join(f"{cid} (not {names[who]})" for cid, who in misses) + ".")

    excluded: set[str] = set()
    rejected: list[tuple[str, str]] = []
    rnd = 0
    for _ in range(max_attempts):
        for a in agents:
            a.reset()
        outcome = negotiate(agents, bus, shared, sc.sections, excluded=frozenset(excluded),
                            start_round=rnd)
        if outcome.status != "agreed":
            for a in agents:
                for msg in bus.receive(human(a.id)):
                    say(f"[to {a.name}] Your agents couldn't find a section that works for everyone. "
                        f"Best-supported options: {', '.join(msg.payload['options']) or 'none'}. "
                        "Let's talk it over together.")
            return FinalPlan(outcome.status, outcome.section_id, rejected=rejected,
                             relaxed=outcome.relaxed)

        sid = outcome.section_id
        section = sc.sections[sid]
        relax = f" after relaxation level {outcome.level}" if outcome.level else ""
        short = (f" It has only {section.seats_left} seats left for {len(agents)} friends."
                 if outcome.needs_swap else "")
        say(phraser.polish(f"Agreement: {sid} ({when(section)}) works for everyone{relax}.{short}", keep))

        rnd = outcome.rounds + 1
        seats = secure_seats(agents, section, list(sc.seat_holders.values()), bus, round=rnd)
        if not seats.ok:
            say(f"No seat in {sid} for {join_names([names[s] for s in seats.stuck])} "
                "(no swap possible). Re-planning.")
            excluded.add(sid)
            rejected.append((sid, "no seat"))
            continue
        if seats.open_seats:
            say(f"{join_names([names[s] for s in seats.open_seats])} take the open seats.")
        for aid, cycle in seats.swaps.items():
            steps = "; ".join(trade(t, names) for t in cycle.trades)
            say(phraser.polish(f"{names[aid]} gets in through a {cycle.size}-way swap: {steps}.", keep))

        no_from = None
        for a in agents:
            say("\n" + briefing(a, sc, sid, seats))
            yes = ask_yes_no(f"{a.name}, confirm this plan? [y/n] ", ask)
            bus.send(a.confirm(sid, yes, round=rnd))
            if not yes:
                no_from = a
                break
        if no_from is None:
            return FinalPlan("confirmed", sid, {a.id: a.plan(sid) for a in agents}, seats,
                             outcome.relaxed, rejected)
        say(f"Nothing is final; re-planning without {sid}.")
        excluded.add(sid)
        rejected.append((sid, no_from.id))

    return FinalPlan("escalated", rejected=rejected)


if __name__ == "__main__":
    bus = MessageBus()
    result = plan_and_confirm(load_scenario(), bus)
    print(f"\nResult: {result.status}" + (f", shared section {result.section_id}" if result.section_id else ""))
    print("\nMessage log:\n" + bus.render())
