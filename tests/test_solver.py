"""Schedule solver: hard rules reject, soft prefs score, shared section is fixed."""

import pytest

from agent import Agent
from course_finder import find_shared_courses
from loader import load_scenario
from models import Constraint, Course, Preference, Section, Student, TimeBlock, parse_time
from solver import best_schedule, shared_section_options


# ---- tiny builders ---------------------------------------------------------

def block(day, start, end, label=""):
    return TimeBlock(day, parse_time(start), parse_time(end), label)


def sec(sid, *meetings, seats=10):
    """sec("A-01", ("Mon", "09:00", "10:00"), ...)"""
    return Section(sid, sid.split("-")[0], tuple(block(*m) for m in meetings), seats)


def course(cid, tags, *sections, credits=3):
    return Course(cid, cid, credits, frozenset(tags), tuple(sections))


def student(reqs, busy=(), hard=(), soft=(), holds=()):
    return Student("s", "S", "Major", frozenset(reqs), tuple(busy), tuple(hard), tuple(soft),
                   tuple(holds), 3.0, ())


def world(*courses):
    catalog = {c.id: c for c in courses}
    return catalog, {s.id: s for c in courses for s in c.sections}


SHARED = course("SH", ["HUM"], sec("SH-01", ("Wed", "11:00", "12:00")))


def solve(st, catalog, sections, strict=()):
    return best_schedule(st, catalog, sections, "SH-01", frozenset({"HUM"}), frozenset(strict))


# ---- hard rules ------------------------------------------------------------

def test_avoids_busy_block():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "09:00", "10:00")),
                                                 sec("A-02", ("Tue", "09:00", "10:00"))))
    st = student({"HUM", "X"}, busy=[block("Mon", "08:00", "18:00", "Clinicals")])
    assert solve(st, cat, secs).assignments == {"HUM": "SH-01", "X": "A-02"}


def test_rejects_sections_that_overlap_each_other():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Wed", "11:30", "12:30")),
                                                 sec("A-02", ("Thu", "11:30", "12:30"))))
    assert solve(student({"HUM", "X"}), cat, secs).assignments["X"] == "A-02"


def test_none_when_nothing_fits():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Wed", "11:00", "12:00"))))
    assert solve(student({"HUM", "X"}), cat, secs) is None


def test_none_when_the_shared_section_itself_clashes():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "09:00", "10:00"))))
    st = student({"HUM", "X"}, busy=[block("Wed", "10:00", "13:00")])
    assert solve(st, cat, secs) is None


def test_max_credits_and_no_after_are_hard():
    cat, secs = world(SHARED,
                      course("BIG", ["X"], sec("BIG-01", ("Mon", "09:00", "10:00")), credits=5),
                      course("LATE", ["X"], sec("LATE-01", ("Tue", "19:00", "20:00"))),
                      course("OK", ["X"], sec("OK-01", ("Thu", "09:00", "10:00"))))
    st = student({"HUM", "X"}, hard=[Constraint("max_credits", 7), Constraint("no_after", parse_time("18:00"))])
    assert solve(st, cat, secs).assignments["X"] == "OK-01"


def test_requirement_with_no_course_means_no_schedule():
    cat, secs = world(SHARED)
    assert solve(student({"HUM", "NOPE"}), cat, secs) is None


def test_one_course_cannot_fill_two_requirements():
    cat, secs = world(SHARED, course("AB", ["X", "Y"], sec("AB-01", ("Mon", "09:00", "10:00"))))
    assert solve(student({"HUM", "X", "Y"}), cat, secs) is None


# ---- seats -----------------------------------------------------------------

def test_skips_full_section_unless_already_held():
    a = course("A", ["X"], sec("A-01", ("Mon", "09:00", "10:00"), seats=0),
                           sec("A-02", ("Tue", "09:00", "10:00")))
    cat, secs = world(SHARED, a)
    assert solve(student({"HUM", "X"}), cat, secs).assignments["X"] == "A-02"
    assert solve(student({"HUM", "X"}, holds=["A-01"]), cat, secs).assignments["X"] == "A-01"


# ---- soft scoring ----------------------------------------------------------

EARLY = Preference("no_before", parse_time("09:00"), 3)
FRI_OFF = Preference("day_off", "Fri", 1)


def test_prefers_section_that_keeps_soft_prefs():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "08:00", "09:00")),
                                                 sec("A-02", ("Mon", "10:00", "11:00"))))
    sched = solve(student({"HUM", "X"}, soft=[EARLY]), cat, secs)
    assert sched.assignments["X"] == "A-02" and sched.cost == 0 and sched.broken == ()


def test_breaks_soft_pref_when_it_is_the_only_option_and_says_which():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "08:00", "09:00"))))
    sched = solve(student({"HUM", "X"}, soft=[EARLY]), cat, secs)
    assert sched.broken == (EARLY,) and sched.cost == 3


def test_strict_pref_acts_as_hard():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "08:00", "09:00"))))
    assert solve(student({"HUM", "X"}, soft=[EARLY]), cat, secs, strict=[EARLY]) is None


def test_breaks_lower_priority_pref_first():
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "08:00", "09:00")),
                                                 sec("A-02", ("Fri", "10:00", "11:00"))))
    sched = solve(student({"HUM", "X"}, soft=[EARLY, FRI_OFF]), cat, secs)
    assert sched.assignments["X"] == "A-02" and sched.broken == (FRI_OFF,)


def test_max_days_counts_the_whole_week():
    few = Preference("max_days", 1, 2)
    cat, secs = world(SHARED, course("A", ["X"], sec("A-01", ("Mon", "09:00", "10:00")),
                                                 sec("A-02", ("Wed", "14:00", "15:00"))))
    assert solve(student({"HUM", "X"}, soft=[few]), cat, secs).assignments["X"] == "A-02"


def test_shared_course_fills_whichever_category_works():
    shared = course("SH", ["HUM", "X"], sec("SH-01", ("Wed", "11:00", "12:00")))
    cat, secs = world(shared, course("A", ["HUM"], sec("A-01", ("Mon", "09:00", "10:00"))))
    sched = best_schedule(student({"HUM", "X"}), cat, secs, "SH-01", frozenset({"HUM", "X"}))
    assert sched.assignments == {"HUM": "A-01", "X": "SH-01"}


def test_deterministic():
    cat, secs = world(SHARED, course("A", ["X"], *[sec(f"A-0{i}", ("Mon", f"0{i}:00", f"0{i}:30"))
                                                    for i in range(1, 6)]))
    results = [solve(student({"HUM", "X"}), cat, secs) for _ in range(5)]
    assert all(r == results[0] for r in results)


# ---- the real scenario -----------------------------------------------------

@pytest.fixture
def scenario():
    sc = load_scenario()
    agents = [Agent(st, sc.catalog, sc.sections) for st in sc.students.values()]
    [shared] = find_shared_courses(sc.catalog, {s.id: set(s.open_requirements) for s in sc.students.values()})
    return sc, {a.id: a for a in agents}, shared


def test_scenario_nothing_fits_everyone_before_relaxing(scenario):
    sc, agents, shared = scenario
    options = shared_section_options(agents.values(), shared, sc.catalog)
    assert not any(o.fits_all for o in options)


def test_scenario_relaxing_bens_friday_unlocks_section_04_but_it_is_short_a_seat(scenario):
    sc, agents, shared = scenario
    ben = agents["ben"]
    ben.relax(ben.active_prefs()[0])
    best = shared_section_options(agents.values(), shared, sc.catalog)[0]
    assert best.section_id == "PHIL215-04" and best.fits_all
    assert best.seats_short == 1 and best.needs_swap


def test_scenario_schedules_around_section_04(scenario):
    sc, agents, shared = scenario
    ben = agents["ben"]
    ben.relax(ben.active_prefs()[0])
    plans = {aid: a.plan("PHIL215-04", shared.counts_as[aid]) for aid, a in agents.items()}
    # Ana gives up her held MATH220-01 (it clashes) for MATH220-02: that seat becomes swap currency.
    assert plans["ana"].assignments["CS_MATH"] == "MATH220-02"
    assert [p.kind for p in plans["ben"].broken] == ["day_off"]
    assert plans["maya"].cost == 0
    maya_days = {m.day for sid in plans["maya"].section_ids for m in sc.sections[sid].meetings}
    assert len(maya_days) <= 3
