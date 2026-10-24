"""Course finder: courses that count for everyone, across different majors."""

from agent import Agent
from bus import MessageBus
from course_finder import categories_from_messages, find_shared_courses, near_misses
from loader import load_scenario
from models import Course


def course(cid, *tags):
    return Course(cid, cid, 3, frozenset(tags), ())


def catalog(*courses):
    return {c.id: c for c in courses}


THREE_MAJORS = {"cs": {"GEN_HUM", "CS_CORE"}, "nurse": {"NURS_ETHICS"}, "biz": {"BUS_ETHICS", "BUS_CORE"}}


def ids(results):
    return [r.course_id for r in results]


def test_one_course_counts_differently_for_each_major():
    cat = catalog(course("ETH", "GEN_HUM", "NURS_ETHICS", "BUS_ETHICS"), course("CS1", "CS_CORE"))
    [shared] = find_shared_courses(cat, THREE_MAJORS)
    assert shared.course_id == "ETH"
    assert shared.counts_as == {"cs": {"GEN_HUM"}, "nurse": {"NURS_ETHICS"}, "biz": {"BUS_ETHICS"}}


def test_two_out_of_three_is_not_enough_and_is_a_near_miss():
    cat = catalog(course("COMM", "GEN_HUM", "BUS_ETHICS"))
    assert find_shared_courses(cat, THREE_MAJORS) == []
    assert near_misses(cat, THREE_MAJORS) == [("COMM", "nurse")]


def test_course_missing_two_students_is_not_a_near_miss():
    cat = catalog(course("CS1", "CS_CORE"))
    assert near_misses(cat, THREE_MAJORS) == []


def test_no_shared_course():
    cat = catalog(course("A", "CS_CORE"), course("B", "NURS_ETHICS"))
    assert find_shared_courses(cat, THREE_MAJORS) == []


def test_reports_every_category_a_course_covers_for_one_student():
    cat = catalog(course("X", "GEN_HUM", "CS_CORE", "NURS_ETHICS", "BUS_CORE"))
    [shared] = find_shared_courses(cat, THREE_MAJORS)
    assert shared.counts_as["cs"] == {"GEN_HUM", "CS_CORE"}
    assert shared.counts_as["biz"] == {"BUS_CORE"}


def test_edge_cases():
    assert find_shared_courses({}, THREE_MAJORS) == []
    assert find_shared_courses(catalog(course("A", "GEN_HUM")), {}) == []
    nothing_open = {**THREE_MAJORS, "done": set()}
    cat = catalog(course("ETH", "GEN_HUM", "NURS_ETHICS", "BUS_ETHICS"))
    assert find_shared_courses(cat, nothing_open) == []


def test_order_is_most_coverage_then_id():
    cat = catalog(
        course("ZZZ", "GEN_HUM", "NURS_ETHICS", "BUS_ETHICS"),
        course("AAA", "GEN_HUM", "NURS_ETHICS", "BUS_ETHICS"),
        course("MID", "GEN_HUM", "CS_CORE", "NURS_ETHICS", "BUS_ETHICS", "BUS_CORE"),
    )
    assert ids(find_shared_courses(cat, THREE_MAJORS)) == ["MID", "AAA", "ZZZ"]
    reversed_cat = dict(reversed(list(cat.items())))
    assert ids(find_shared_courses(reversed_cat, THREE_MAJORS)) == ["MID", "AAA", "ZZZ"]


def test_real_scenario():
    sc = load_scenario()
    cats = {sid: set(s.open_requirements) for sid, s in sc.students.items()}
    assert ids(find_shared_courses(sc.catalog, cats)) == ["PHIL215"]
    assert near_misses(sc.catalog, cats) == [
        ("COMM220", "ben"), ("HSCI230", "ana"), ("MATH220", "ben"),
    ]


def test_works_from_messages_shared_on_the_bus():
    sc = load_scenario()
    bus = MessageBus()
    agents = [Agent(st, sc.catalog, sc.sections) for st in sc.students.values()]
    own = {}
    for a in agents:
        bus.register(a.id)
    for a in agents:
        own[a.id] = a.share_open_categories()
        bus.send(own[a.id])
    # Each agent can run the finder on its own: its own share plus what it received.
    for a in agents:
        cats = categories_from_messages([own[a.id], *bus.receive(a.id)])
        assert set(cats) == {"ana", "ben", "maya"}
        assert ids(find_shared_courses(sc.catalog, cats)) == ["PHIL215"]
