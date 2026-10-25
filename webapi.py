"""Bridge between the Co-Register engine and the demo web page.

The page runs this file in the browser (through Pyodide, Python compiled to WebAssembly).
`run(options_json)` takes a few visitor-chosen changes, runs the real `plan_and_confirm()`
engine, and returns everything the page needs as JSON: the ordered timeline of what
happened, each student's private briefing, the swap, the schedules and the privacy audit.

Nothing here decides anything. All negotiation, solving and swap-finding is done by the
same modules `run_demo.py` uses. This file only changes the starting data, records what
happens, and reshapes it.

Try it locally:  python3 webapi.py            (prints the base scenario as JSON)
"""

from __future__ import annotations

import json
from dataclasses import replace

from bus import MessageBus
from confirm import names_of, plan_and_confirm
from loader import Scenario, load_scenario
from models import Preference
from phrasing import Phraser, narrate
from solver import show

PHIL_SECTION = "PHIL215-04"

DEFAULTS = {
    "ben_friday_priority": 1,      # 0 = Ben has no Friday preference, otherwise its priority (1-3)
    "maya_max_days": 3,            # None = no limit; else classes on at most this many days (soft, priority 2)
    "ana_no_early": True,          # Ana would rather not start before 9:00 (soft, priority 3)
    "seats_left": 2,               # open seats left in PHIL215-04
    "priya_willing": True,         # will Priya give up the PHIL215-04 seat in a swap?
    "say_no_first": [],            # student ids who answer "no" the first time they are asked
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
    return o


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
    out = [{"hard": True, "text": show(c)} for c in student.hard_constraints]
    out += [{"hard": False, "text": show(p), "priority": p.priority} for p in student.soft_prefs]
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
    state = {"phase": None, "asked": set()}
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
        no = sid in o["say_no_first"] and sid not in state["asked"]
        state["asked"].add(sid)
        timeline.append({"kind": "ask", "student": sid, "name": who, "answer": "n" if no else "y"})
        return "n" if no else "y"

    bus = MessageBus(listener=on_message)
    result = plan_and_confirm(sc, bus, ask=ask, say=say, phraser=Phraser())

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
        "sections": {sid: _section_info(sc, sid) for sid in sorted(used | {PHIL_SECTION})},
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
