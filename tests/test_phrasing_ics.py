"""Phrasing templates, the LLM fact guard, and .ics output."""

from datetime import date

from bus import LogEntry
from ics import calendar
from loader import load_scenario
from models import Preference, parse_time
from phrasing import Phraser, clock, describe_pref, narrate, trade, when
from swaps import Trade


# ---- templates -------------------------------------------------------------

def test_describe_prefs_in_plain_english():
    assert describe_pref(Preference("day_off", "Fri", 1)) == "Fridays off"
    assert describe_pref(Preference("no_before", parse_time("09:00"), 3)) == "no classes before 9:00 AM"
    assert describe_pref(Preference("max_days", 3, 2)) == "classes on at most 3 days"
    assert clock(parse_time("18:00")) == "6:00 PM" and clock(parse_time("12:30")) == "12:30 PM"


def test_when_groups_days_and_marks_labs():
    sc = load_scenario()
    assert when(sc.sections["PHIL215-04"]) == "Wed/Fri 11:00-12:15"
    assert when(sc.sections["BIO240-01"]) == "Tue/Thu 09:00-10:15, Tue 14:00-16:50 lab"


def test_trade_wording_from_each_point_of_view():
    names = {"ana": "Ana", "priya": "Priya"}
    t = Trade("priya", "PHIL215-04", "ana")
    assert trade(t, names) == "Priya gives their PHIL215-04 seat to Ana"
    assert trade(t, names, viewer="ana") == "Priya gives their PHIL215-04 seat to you"
    assert trade(Trade("ana", "MATH220-01", "priya"), names, viewer="ana") == "You give your MATH220-01 seat to Priya"


def test_narrate_decline_never_adds_a_reason():
    entry = LogEntry(1, 1, "ben", "ana", "DECLINE", ["section_id"], {"section_id": "PHIL215-04"})
    assert narrate(entry, {"ben": "Ben"}, {}) == "    Ben's agent: decline (no reason shared)"


# ---- LLM guard -------------------------------------------------------------

LINE = "Agreement: PHIL215-04 (Wed/Fri 11:00-12:15) works for everyone after relaxation level 1."


def test_no_llm_means_template_text():
    assert Phraser().polish(LINE) == LINE and not Phraser().uses_llm


def test_llm_rewording_kept_when_facts_survive():
    good = "Great news: everyone can make PHIL215-04 (Wed/Fri 11:00-12:15), after relaxation level 1!"
    assert Phraser(lambda _: good).polish(LINE) == good


def test_llm_rewording_rejected_when_a_fact_changes_or_disappears():
    for bad in ["Everyone agreed on PHIL215-03 (Wed/Fri 11:00-12:15) at level 1.",  # wrong section
                "Everyone agreed on a section!",                                    # facts dropped
                "", "line one\nline two"]:
        assert Phraser(lambda _, b=bad: b).polish(LINE) == LINE


def test_llm_names_must_survive():
    line = "Ben and Maya take the open seats."
    assert Phraser(lambda _: "Two friends take the open seats.").polish(line, keep=("Ben", "Maya")) == line


def test_llm_errors_fall_back_to_template():
    def boom(_):
        raise RuntimeError("network down")
    assert Phraser(boom).polish(LINE) == LINE


def test_from_env_without_flag_is_offline():
    assert not Phraser.from_env(use_llm=False).uses_llm


# ---- .ics ------------------------------------------------------------------

def test_calendar_has_weekly_events_on_the_right_days():
    sc = load_scenario()
    text = calendar("Ben", [sc.sections["PHIL215-04"], sc.sections["BIO240-01"]], sc.catalog,
                    start=date(2027, 1, 19), end=date(2027, 5, 7))
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 3  # PHIL Wed/Fri, BIO lecture Tue/Thu, BIO lab Tue
    assert "DTSTART:20270120T110000" in text  # first Wednesday on/after Tue Jan 19
    assert "RRULE:FREQ=WEEKLY;UNTIL=20270507T235959;BYDAY=WE,FR" in text
    assert "DTSTART:20270119T140000" in text and "BYDAY=TU\r\n" in text  # the lab
    assert "SUMMARY:PHIL215 Ethics in Technology\\, Health & Business" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_calendar_is_deterministic():
    sc = load_scenario()
    secs = [sc.sections["CS201-01"]]
    assert calendar("Ana", secs, sc.catalog) == calendar("Ana", secs, sc.catalog)
