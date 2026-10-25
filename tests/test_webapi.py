"""The demo page's bridge: private "peek" notes stay off the bus; answers drive re-plans."""

import json

import agent
import confirm
import webapi


def run(**options):
    return json.loads(webapi.run(json.dumps(options)))


def test_peek_notes_are_recorded_but_never_sent():
    r = run()
    msgs = [t for t in r["timeline"] if t["kind"] == "msg"]
    ben_no = next(t for t in msgs if t["type"] == "DECLINE" and t["sender"] == "ben")
    assert "Clinicals" in ben_no["thought"]
    relax = next(t for t in msgs if t["type"] == "RELAX")
    assert relax["relaxed_private"] == {"ana": [], "ben": ["Fridays off"], "maya": []}
    # The messages themselves carry only whitelisted fields, and the audit still finds nothing.
    for t in msgs:
        assert set(t["payload"]) == set(t["fields"])
        assert "thought" not in json.dumps(t["payload"]) and "Fridays" not in json.dumps(t["payload"])
    assert r["audit"]["leaks"] == 0


def test_real_agent_is_restored():
    run()
    assert confirm.Agent is agent.Agent


def test_answers_match_say_no_first():
    by_answers = run(answers=["y", "n"])
    by_flag = run(say_no_first=["ben"])
    assert by_answers["timeline"] == by_flag["timeline"]
    assert by_answers["result"]["section_id"] == "PHIL215-03"


def test_runs_with_the_same_answers_share_a_prefix():
    # The page relies on this: a visitor's "no" re-runs the engine and continues from that point.
    base, replan = run(), run(answers=["y", "n"])
    k = next(i for i, t in enumerate(base["timeline"]) if t["kind"] == "ask" and t["student"] == "ben")
    assert base["timeline"][:k] == replan["timeline"][:k]


def test_calendars_for_every_confirmed_student():
    r = run()
    assert set(r["calendars"]) == {"ana", "ben", "maya"}
    assert "SUMMARY:PHIL215" in r["calendars"]["ben"]
    assert run(say_no_first=["ana", "ben"])["calendars"] == {}
