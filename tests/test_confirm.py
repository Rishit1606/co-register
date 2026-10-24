"""Human confirmation: all-yes, a no triggers a re-plan, escalation, privacy of briefings."""

import pytest

from bus import MessageBus
from confirm import plan_and_confirm
from loader import load_scenario


def scripted(*answers):
    """Stand-in for input(): returns the answers in order and records each prompt."""
    it = iter(answers)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return next(it)
    ask.prompts = prompts
    return ask


@pytest.fixture
def sc():
    return load_scenario()


def run(sc, *answers):
    bus, said = MessageBus(), []
    ask = scripted(*answers)
    result = plan_and_confirm(sc, bus, ask=ask, say=said.append)
    return result, bus, "\n".join(said), ask.prompts


def confirmations(bus):
    """(sender, type, section) for the students' final answers (broadcast ACCEPT/DECLINE)."""
    return [(e.sender, e.type, e.payload["section_id"]) for e in bus.log
            if e.recipient == "all" and e.type in ("ACCEPT", "DECLINE")]


def test_everyone_says_yes(sc):
    result, bus, _, prompts = run(sc, "y", "y", "y")
    assert result.status == "confirmed" and result.section_id == "PHIL215-04"
    assert result.seats.swaps["ana"].size == 3
    assert result.relaxed == {"ben": ["day_off Fri"]}
    assert confirmations(bus) == [("ana", "ACCEPT", "PHIL215-04"), ("ben", "ACCEPT", "PHIL215-04"),
                                  ("maya", "ACCEPT", "PHIL215-04")]
    assert [p.split(",")[0] for p in prompts] == ["Ana", "Ben", "Maya"]
    assert set(result.schedules) == {"ana", "ben", "maya"}


def test_one_no_triggers_a_replan(sc):
    result, bus, said, _ = run(sc, "y", "n", "y", "y", "y")
    assert result.status == "confirmed" and result.section_id == "PHIL215-03"
    assert result.rejected == [("PHIL215-04", "ben")]
    assert ("ben", "DECLINE", "PHIL215-04") in confirmations(bus)
    assert "Ben said no to PHIL215-04" in said
    # The re-plan started from full preferences, then had to relax further.
    assert set(result.relaxed) == {"ana", "ben", "maya"}
    # Round numbers keep increasing across the re-plan.
    rounds = [e.round for e in bus.log]
    assert rounds == sorted(rounds)


def test_decline_carries_no_reason(sc):
    _, bus, _, _ = run(sc, "y", "n", "y", "y", "y")
    [decline] = [e for e in bus.log if e.recipient == "all" and e.type == "DECLINE"]
    assert decline.payload == {"section_id": "PHIL215-04"}


def test_unclear_answers_are_asked_again(sc):
    result, _, _, prompts = run(sc, "maybe", "", "YES", "y", "y")
    assert result.status == "confirmed" and len(prompts) == 5


def test_repeated_no_ends_in_escalation(sc):
    result, _, said, _ = run(sc, "n", "n")
    assert result.status == "escalated"
    assert [r[0] for r in result.rejected] == ["PHIL215-04", "PHIL215-03"]
    for name in ("Ana", "Ben", "Maya"):
        assert f"[to {name}] Your agents couldn't find a section" in said


def test_no_seat_means_automatic_replan(sc):
    sc.seat_holders.pop("quinn")  # breaks the 3-way swap for PHIL215-04
    result, _, said, prompts = run(sc, "y", "y", "y")
    assert result.rejected == [("PHIL215-04", "no seat")]
    assert "No seat in PHIL215-04 for ana" in said
    assert result.status == "confirmed" and result.section_id == "PHIL215-03"


def test_briefings_are_private_but_the_bus_is_clean(sc):
    _, bus, said, _ = run(sc, "y", "y", "y")
    ben_briefing = said.split("--- Private to Ben ---")[1].split("--- Private to")[0]
    ana_briefing = said.split("--- Private to Ana ---")[1].split("--- Private to")[0]
    assert "day_off Fri" in ben_briefing and "day_off Fri" not in ana_briefing
    assert "3-way swap" in ana_briefing
    log = bus.render().lower()
    for st in sc.students.values():
        for secret in [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]:
            assert secret.lower() not in log
    assert "day_off" not in log and "relaxed" not in log
