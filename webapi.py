"""Bridge between the Co-Register engine and the demo web page.

The page runs this file in the browser (through Pyodide, Python compiled to WebAssembly).
`run(options_json)` takes a few visitor-chosen changes, runs the real `plan_and_confirm()`
engine, and returns everything the page needs as JSON: the ordered timeline of what
happened, each student's private briefing, the swap, the schedules and the privacy audit.

Nothing here decides anything. All negotiation, solving and swap-finding is done by the
same modules `run_demo.py` uses. This file only changes the starting data, records what
happens, and reshapes it.

The page has a "peek inside an agent" view. To fill it, the agents are swapped for a
RecordingAgent subclass that writes down each agent's PRIVATE reason for accepting or
declining. Those notes go into this JSON (the page plays the role of each student's own
screen), never onto the bus, so the privacy audit below still scans exactly what agents sent.

Try it locally:  python3 webapi.py            (prints the base scenario as JSON)
"""

from __future__ import annotations

import json
from dataclasses import replace

import confirm
from agent import Agent
from bus import MessageBus
from confirm import names_of, plan_and_confirm
from ics import calendar
from loader import Scenario, load_scenario
from models import MessageType, Preference
from phrasing import Phraser, describe_pref, narrate
from solver import best_schedule, breaks, show

PHIL_SECTION = "PHIL215-04"

DEFAULTS = {
    "ben_friday_priority": 1,      # 0 = Ben has no Friday preference, otherwise its priority (1-3)
    "maya_max_days": 3,            # None = no limit; else classes on at most this many days (soft, priority 2)
    "ana_no_early": True,          # Ana would rather not start before 9:00 (soft, priority 3)
    "seats_left": 2,               # open seats left in PHIL215-04
    "priya_willing": True,         # will Priya give up the PHIL215-04 seat in a swap?
    "say_no_first": [],            # student ids who answer "no" the first time they are asked
    "answers": [],                 # "y"/"n" in the order students are asked; overrides say_no_first
}

PHASES = {
    "share": "1. Each agent shares only what its policy allows",
    "find": "2. Find a class that counts for every major",
    "negotiate": "3. Negotiate a section (conflicting constraints)",
    "seats": "4. Get everyone a seat",
    "confirm": "5. Each student confirms (nothing is final until all say yes)",
    "privacy": "6. Privacy audit: what crossed the bus",
}


def _clean(options: dict) -> dict:
    """Merge with defaults and coerce types so a messy browser value can't crash the engine."""
    o = {**DEFAULTS, **(options or {})}
    o["ben_friday_priority"] = max(0, min(3, int(o["ben_friday_priority"] or 0)))
    mmd = o["maya_max_days"]
    o["maya_max_days"] = None if mmd in (None, "", 0, "none") else max(1, min(5, int(mmd)))
    o["ana_no_early"] = bool(o["ana_no_early"])
    o["seats_left"] = max(0, min(5, int(o["seats_left"])))
    o["priya_willing"] = bool(o["priya_willing"])
    o["say_no_first"] = [s for s in o["say_no_first"] if s in ("ana", "ben", "maya")]
    o["answers"] = [a for a in (o["answers"] or []) if a in ("y", "n")][:24]
    return o


class _Notes:
    """What the agents thought privately during one run, for the page's peek view."""

    def __init__(self):
        self.thoughts: dict[tuple, str] = {}   # (sender, type, section_id, round) -> private reason
        self.relaxed: dict[str, list[str]] | None = None  # the current RELAX: agent id -> what it dropped


def _recording_agent(notes: _Notes) -> type[Agent]:
    """An Agent that behaves identically but writes down its private reasons in `notes`."""

    class RecordingAgent(Agent):
        def why_not(self, sid: str) -> str:
            st, sec = self._student, self._sections[sid]
            course = self._catalog[sec.course_id]
            loose = best_schedule(st, self._catalog, self._sections, sid,
                                  frozenset(course.tags & st.open_requirements))
            if loose is not None:
                active = set(self.active_prefs())
                hit = [p for p in loose.broken if p in active]
                if hit:
                    return "It would break " + " and ".join(
                        f"{describe_pref(p)} (a preference, importance {p.priority})" for p in hit) + "."
            labels = sorted({b.label for m in sec.meetings for b in st.busy_blocks if m.overlaps(b)})
            if labels:
                return f"It clashes with {'; '.join(labels)}. That can't move."
            rules = [describe_pref(c) for c in st.hard_constraints
                     if breaks(c.kind, c.value, [sec], course.credits)]
            if rules:
                return f"It breaks a hard rule: {', '.join(rules)}."
            return "No full week fits around it: the other required classes clash or go over a limit."

        def why_yes(self, sid: str) -> str:
            plan = self.plan(sid)
            given_up = [describe_pref(p) for p in plan.broken] if plan else []
            if given_up:
                return f"A full week fits by giving up {' and '.join(given_up)}."
            return "A full week fits around it, with nothing given up."

        def respond(self, proposal):
            msg = super().respond(proposal)
            sid = msg.payload["section_id"]
            notes.thoughts[(self.id, msg.type.value, sid, msg.round)] = (
                self.why_yes(sid) if msg.type is MessageType.ACCEPT else self.why_not(sid))
            return msg

        def recheck(self, declined, to, round=0):
            msgs = super().recheck(declined, to, round)
            for m in msgs:
                sid = m.payload["section_id"]
                notes.thoughts[(self.id, "ACCEPT", sid, round)] = "Now it works. " + self.why_yes(sid)
            return msgs

        def call_relax(self, level, round=0):
            notes.relaxed = {}
            return super().call_relax(level, round)

        def relax_to(self, level):
            newly = super().relax_to(level)
            if notes.relaxed is not None:
                notes.relaxed[self.id] = [describe_pref(p) for p in newly]
            return newly

    return RecordingAgent


def apply_options(sc: Scenario, o: dict) -> None:
    """Change the starting data in place. Only inputs change; the engine is untouched."""
    ana, ben, maya = sc.students["ana"], sc.students["ben"], sc.students["maya"]

    def keep(student, kinds):
        return tuple(p for p in student.soft_prefs if p.kind not in kinds)

    ana.soft_prefs = keep(ana, {"no_before"}) + (
        (Preference("no_before", 9 * 60, 3),) if o["ana_no_early"] else ())
    ben.soft_prefs = keep(ben, {"day_off"}) + (
        (Preference("day_off", "Fri", o["ben_friday_priority"]),) if o["ben_friday_priority"] else ())
    maya.soft_prefs = keep(maya, {"max_days"}) + (
        (Preference("max_days", o["maya_max_days"], 2),) if o["maya_max_days"] else ())

    section = sc.sections[PHIL_SECTION]
    new_section = replace(section, seats_left=o["seats_left"])
    course = sc.catalog[section.course_id]
    sc.catalog[course.id] = replace(
        course, sections=tuple(new_section if s.id == section.id else s for s in course.sections))
    sc.sections[section.id] = new_section

    if not o["priya_willing"]:
        sc.seat_holders["priya"] = replace(sc.seat_holders["priya"], would_accept=())


def _rules(student) -> list[dict]:
    """A student's private rules, for the 'what stays private' panel (mock data)."""
    out = [{"hard": True, "text": show(c), "label": describe_pref(c)} for c in student.hard_constraints]
    out += [{"hard": False, "text": show(p), "label": describe_pref(p), "priority": p.priority}
            for p in student.soft_prefs]
    return out


def _section_info(sc: Scenario, section_id: str) -> dict:
    s = sc.sections[section_id]
    c = sc.catalog[s.course_id]
    return {
        "id": s.id, "course_id": c.id, "title": c.title, "seats_left": s.seats_left,
        "meetings": [{"day": m.day, "start": m.start, "end": m.end, "label": m.label} for m in s.meetings],
    }


def run(options_json: str = "{}") -> str:
    o = _clean(json.loads(options_json or "{}"))
    sc = load_scenario()
    apply_options(sc, o)
    names = names_of(sc)
    sections = sc.sections

    timeline: list[dict] = []
    state = {"phase": None, "asked": set(), "asks": 0}
    peek = _Notes()
    briefings: dict[str, str] = {}
    notes: list[str] = []

    def phase(key: str) -> None:
        if key != state["phase"]:
            state["phase"] = key
            timeline.append({"kind": "phase", "key": key, "title": PHASES[key]})

    def on_message(entry) -> None:
        if entry.type == "SHARE":
            phase("share")
        elif entry.type in ("PROPOSE", "COUNTER", "RELAX", "ESCALATE_TO_HUMAN"):
            phase("negotiate")
        elif entry.type == "SWAP_OFFER":
            phase("seats")
        timeline.append({
            "kind": "msg", "seq": entry.seq, "round": entry.round, "type": entry.type,
            "sender": entry.sender, "sender_name": names.get(entry.sender, entry.sender),
            "recipient": entry.recipient, "recipient_name": names.get(entry.recipient, entry.recipient),
            "fields": entry.fields, "payload": entry.payload,
            "text": narrate(entry, names, sections),
        })
        # Private side, for the peek view only. Never part of the message itself.
        if entry.type in ("ACCEPT", "DECLINE"):
            key = (entry.sender, entry.type, entry.payload.get("section_id"), entry.round)
            if key in peek.thoughts:
                timeline[-1]["thought"] = peek.thoughts.pop(key)
        elif entry.type == "RELAX":
            timeline[-1]["relaxed_private"] = peek.relaxed  # filled in as each agent relaxes

    def say(text: str) -> None:
        if state["phase"] == "share":
            phase("find")
        stripped = text.lstrip()
        if stripped.startswith("--- Private to"):
            phase("confirm")
            who = stripped.split("--- Private to ", 1)[1].split(" ---", 1)[0]
            sid = next(s.id for s in sc.students.values() if s.name == who)
            briefings[sid] = stripped
            timeline.append({"kind": "briefing", "student": sid, "text": stripped})
            return
        if state["phase"] == "negotiate" and "take the open seats" in text:
            phase("seats")
        notes.append(text)
        timeline.append({"kind": "note", "text": text})

    def ask(prompt: str) -> str:
        who = prompt.split(",", 1)[0]
        sid = next(s.id for s in sc.students.values() if s.name == who)
        if state["asks"] < len(o["answers"]):
            answer = o["answers"][state["asks"]]
        else:
            answer = "n" if sid in o["say_no_first"] and sid not in state["asked"] else "y"
        state["asked"].add(sid)
        timeline.append({"kind": "ask", "student": sid, "name": who, "answer": answer,
                         "index": state["asks"]})
        state["asks"] += 1
        return answer

    bus = MessageBus(listener=on_message)
    real_agent = confirm.Agent
    confirm.Agent = _recording_agent(peek)
    try:
        result = plan_and_confirm(sc, bus, ask=ask, say=say, phraser=Phraser())
    finally:
        confirm.Agent = real_agent

    phase("privacy")
    audit = bus.audit()
    secrets = [v for st in sc.students.values()
               for v in [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]]
    text = json.dumps([e.payload for e in bus.log]).lower()
    leaks = [s for s in secrets if s.lower() in text]

    level = 0
    for n in notes:
        if n.startswith("Agreement:") and "relaxation level" in n:
            level = int(n.split("relaxation level", 1)[1].strip().split(".")[0].split()[0])

    used = set()
    proposed = {t["payload"]["section_id"] for t in timeline
                if t["kind"] == "msg" and t["type"] in ("PROPOSE", "COUNTER")}
    schedules = {}
    for sid, sched in result.schedules.items():
        used.update(sched.section_ids)
        schedules[sid] = {"section_ids": list(sched.section_ids),
                          "assignments": sched.assignments, "cost": sched.cost}
    swaps = {}
    if result.seats:
        for fid, cyc in result.seats.swaps.items():
            swaps[fid] = [{"giver": t.giver, "giver_name": names[t.giver], "section_id": t.section_id,
                           "receiver": t.receiver, "receiver_name": names[t.receiver]} for t in cyc.trades]
            used.update(t.section_id for t in cyc.trades)

    out = {
        "options": o,
        "students": [{
            "id": s.id, "name": s.name, "major": s.major, "needs": sorted(s.open_requirements),
            "private": {
                "gpa": s.gpa, "transcript": list(s.transcript),
                "busy": sorted({b.label for b in s.busy_blocks}),
                "blocks": [{"day": b.day, "start": b.start, "end": b.end, "label": b.label}
                           for b in s.busy_blocks],
                "rules": _rules(s),
            },
        } for s in sc.students.values()],
        "seat_holders": [{"id": h.id, "name": h.name, "holds": h.holds} for h in sc.seat_holders.values()],
        "timeline": timeline,
        "briefings": briefings,
        "result": {
            "status": result.status,
            "section_id": result.section_id,
            "level": level,
            "rejected": [{"section_id": sid, "by": by, "by_name": names.get(by, by)}
                         for sid, by in result.rejected],
            "open_seats": list(result.seats.open_seats) if result.seats else [],
            "stuck": list(result.seats.stuck) if result.seats else [],
            "swaps": swaps,
            "schedules": schedules,
        },
        "calendars": {sid: calendar(sc.students[sid].name, [sc.sections[x] for x in sched.section_ids],
                                    sc.catalog)
                      for sid, sched in result.schedules.items()},
        "sections": {sid: _section_info(sc, sid) for sid in sorted(used | proposed | {PHIL_SECTION})},
        "audit": {
            "shared_fields": audit,
            "messages": len(bus.log),
            "private_values": len(secrets),
            "leaks": len(leaks),
        },
    }
    return json.dumps(out)


if __name__ == "__main__":
    print(json.dumps(json.loads(run("{}")), indent=2)[:3000])
