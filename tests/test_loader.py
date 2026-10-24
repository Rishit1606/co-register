"""The mock data loads, and still tells the story the demo depends on."""

import json

import pytest

from loader import DATA_DIR, load_scenario
from models import TimeBlock, parse_time


@pytest.fixture(scope="module")
def sc():
    return load_scenario()


def test_everything_loads(sc):
    assert set(sc.students) == {"ana", "ben", "maya"}
    assert len(sc.catalog) >= 10
    assert set(sc.seat_holders) == {"priya", "quinn", "raj", "sam"}


def test_times_are_minutes_and_meetings_expand_per_day(sc):
    phil04 = sc.sections["PHIL215-04"]
    assert [str(m) for m in phil04.meetings] == ["Wed 11:00-12:15", "Fri 11:00-12:15"]
    assert phil04.meetings[0].start == 660
    ana_pref = sc.students["ana"].soft_prefs[0]
    assert (ana_pref.kind, ana_pref.value) == ("no_before", parse_time("09:00"))


def test_overlap():
    a = TimeBlock("Wed", 660, 735)
    assert a.overlaps(TimeBlock("Wed", 700, 760))
    assert not a.overlaps(TimeBlock("Wed", 735, 800))  # back-to-back is fine
    assert not a.overlaps(TimeBlock("Fri", 660, 735))


def test_phil215_is_the_only_course_for_all_three_majors(sc):
    shared = [
        c.id for c in sc.catalog.values()
        if all(c.tags & s.open_requirements for s in sc.students.values())
    ]
    assert shared == ["PHIL215"]
    # Each friend needs it for a DIFFERENT reason.
    reasons = {s.id: sc.catalog["PHIL215"].tags & s.open_requirements for s in sc.students.values()}
    assert reasons == {"ana": {"GEN_HUM"}, "ben": {"NURS_ETHICS"}, "maya": {"BUS_ETHICS"}}


def test_best_shared_section_is_one_seat_short(sc):
    assert sc.sections["PHIL215-04"].seats_left == len(sc.students) - 1


def test_three_way_swap_cycle_exists_in_data(sc):
    ana, priya, quinn = sc.students["ana"], sc.seat_holders["priya"], sc.seat_holders["quinn"]
    assert "MATH220-01" in ana.holds and sc.sections["MATH220-01"].is_full
    assert priya.holds == "PHIL215-04" and "BIO240-02" in priya.would_accept
    assert quinn.holds == "BIO240-02" and "MATH220-01" in quinn.would_accept
    # Ana's held seat clashes with the shared section, which is why she'd trade it.
    assert any(
        a.overlaps(b)
        for a in sc.sections["MATH220-01"].meetings
        for b in sc.sections["PHIL215-04"].meetings
    )


def test_bad_reference_is_rejected(tmp_path):
    for name in ("catalog.json", "students.json"):
        (tmp_path / name).write_text((DATA_DIR / name).read_text())
    (tmp_path / "seat_holders.json").write_text(json.dumps(
        {"seat_holders": [{"id": "x", "name": "X", "holds": "NOPE-01", "would_accept": []}]}
    ))
    with pytest.raises(ValueError, match="unknown section"):
        load_scenario(tmp_path)
