"""Negotiation: propose/counter rounds, privacy-preserving relaxation, escalation."""

from dataclasses import replace

import pytest

from agent import Agent
from bus import MessageBus, human
from course_finder import find_shared_courses
from loader import load_scenario
from models import MessageType, TimeBlock, parse_time
from negotiation import negotiate


@pytest.fixture
def sc():
    return load_scenario()


def run(sc, students=None, excluded=frozenset(), catalog=None):
    students = students or sc.students
    catalog = catalog or sc.catalog
    bus = MessageBus()
    agents = [Agent(st, catalog, sc.sections) for st in students.values()]
    for a in agents:
        bus.register(a.id)
    shared = find_shared_courses(catalog, {s.id: set(s.open_requirements) for s in students.values()})
    return negotiate(agents, bus, shared, sc.sections, excluded=excluded), bus


def types(bus):
    return [e.type for e in bus.log]


def test_scenario_agrees_on_section_04_after_relaxing_only_bens_friday(sc):
    out, bus = run(sc)
    assert (out.status, out.section_id, out.level) == ("agreed", "PHIL215-04", 1)
    assert out.relaxed == {"ben": ["day_off Fri"]}
    assert out.needs_swap and out.seats_short == 1
    assert {"PROPOSE", "COUNTER", "DECLINE", "ACCEPT", "RELAX"} <= set(types(bus))
    assert types(bus)[-2:] == ["ACCEPT", "ACCEPT"]


def test_relax_message_reveals_only_the_level(sc):
    _, bus = run(sc)
    [relax] = [e for e in bus.log if e.type == "RELAX"]
    assert relax.payload == {"level": 1}


def test_log_never_leaks_private_data(sc):
    _, bus = run(sc)
    text = bus.render().lower()
    for st in sc.students.values():
        for secret in [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]:
            assert secret.lower() not in text
    for word in ("day_off", "max_days", "no_before", "priority", "soft", "hard"):
        assert word not in text


def test_no_relaxation_when_something_already_fits(sc):
    students = dict(sc.students, ben=replace(sc.students["ben"], soft_prefs=()))
    out, bus = run(sc, students)
    assert out.status == "agreed" and out.level == 0 and out.relaxed == {}
    assert "RELAX" not in types(bus)


def test_one_no_excludes_a_section_and_forces_deeper_relaxation(sc):
    out, _ = run(sc, excluded=frozenset({"PHIL215-04"}))
    assert (out.status, out.section_id, out.level) == ("agreed", "PHIL215-03", 3)
    assert set(out.relaxed) == {"ana", "ben", "maya"}


def test_escalates_to_every_human_when_nothing_ever_fits(sc):
    wed_busy = TimeBlock("Wed", parse_time("07:00"), parse_time("21:00"), "Work: double shift")
    ana = sc.students["ana"]
    students = dict(sc.students, ana=replace(ana, busy_blocks=ana.busy_blocks + (wed_busy,)))
    out, bus = run(sc, students)
    assert out.status == "escalated" and out.level == 3
    for sid in ("ana", "ben", "maya"):
        [msg] = bus.receive(human(sid))
        assert msg.type is MessageType.ESCALATE_TO_HUMAN
        assert msg.payload["section_id"] == out.section_id
        assert set(msg.payload["options"]) <= {s.id for s in sc.catalog["PHIL215"].sections}


def test_no_shared_course(sc):
    catalog = {cid: c for cid, c in sc.catalog.items() if cid != "PHIL215"}
    out, bus = run(sc, catalog=catalog)
    assert out.status == "no_shared_course" and bus.log == []
