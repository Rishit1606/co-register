"""The privacy story: private fields never appear in any message an agent builds."""

import json

import pytest

from agent import Agent, PolicyViolation, SharePolicy
from loader import load_scenario
from models import Message, MessageType

PHIL = ["PHIL215-01", "PHIL215-02", "PHIL215-03", "PHIL215-04"]


@pytest.fixture(scope="module")
def sc():
    return load_scenario()


@pytest.fixture
def agents(sc):
    return {sid: Agent(st, sc.catalog, sc.sections) for sid, st in sc.students.items()}


def every_message(agent: Agent, others: list[Agent]) -> list[Message]:
    """Everything an agent can possibly say, to drive the leak check."""
    msgs = [agent.share_open_categories(), agent.share_free_windows()]
    for sid in PHIL:
        msgs.append(agent.propose(sid))
        msgs.append(agent.propose(sid, counter=True))
        for other in others:
            msgs.append(agent.respond(other.propose(sid)))
    msgs.append(agent.swap_offer("MATH220-01", "PHIL215-04", "quinn"))
    msgs.append(agent.escalate("PHIL215-04", ["PHIL215-03", "PHIL215-04"]))
    return msgs


def as_text(msg: Message) -> str:
    return json.dumps({"sender": msg.sender, "recipient": msg.recipient,
                       "type": msg.type.value, "payload": msg.payload}).lower()


@pytest.mark.parametrize("student_id", ["ana", "ben", "maya"])
def test_no_private_field_leaks(sc, agents, student_id):
    st = sc.students[student_id]
    others = [a for k, a in agents.items() if k != student_id]
    text = "\n".join(as_text(m) for m in every_message(agents[student_id], others))

    secrets = [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]
    # Distinctive words from the job/clinical details, in case a label is split up.
    secrets += ["help desk", "library", "clinical", "st. vincent", "hospital", "work"]
    secrets += ["soft", "hard", "priority", "reason", "no_before", "no_after",
                "day_off", "max_days", "max_credits"]
    for secret in secrets:
        assert secret.lower() not in text, f"{student_id} leaked {secret!r}"


def test_messages_carry_only_whitelisted_fields(agents):
    others = list(agents.values())
    for agent in agents.values():
        for msg in every_message(agent, others):
            assert set(msg.payload) <= {"open_categories", "free_windows", "section_id",
                                        "course_id", "give_section", "want_section", "options"}


def test_decline_says_nothing_but_the_section(agents):
    decline = agents["ben"].respond(agents["ana"].propose("PHIL215-01"))
    assert decline.type is MessageType.DECLINE
    assert decline.payload == {"section_id": "PHIL215-01"}
    assert decline.recipient == "ana"


def test_policy_rejects_extra_field():
    policy = SharePolicy([])
    with pytest.raises(PolicyViolation, match="reason"):
        policy.check(MessageType.DECLINE, {"section_id": "X", "reason": "I work then"})
    with pytest.raises(PolicyViolation, match="gpa"):
        policy.check(MessageType.SHARE, {"gpa": 3.9})


def test_policy_rejects_private_value_in_allowed_field(sc):
    policy = SharePolicy.for_student(sc.students["ben"])
    with pytest.raises(PolicyViolation, match="private"):
        policy.check(MessageType.PROPOSE, {"section_id": "Clinicals: med-surg rotation at St. Vincent Hospital"})
    with pytest.raises(PolicyViolation, match="private"):
        policy.check(MessageType.SHARE, {"open_categories": ["3.41"]})


def test_policy_rejects_hard_soft_hints():
    with pytest.raises(PolicyViolation, match="forbidden"):
        SharePolicy([]).check(MessageType.SHARE, {"open_categories": ["soft:day_off"]})


def test_free_windows_hide_why(agents):
    ben = agents["ben"].free_windows()
    mon = [w for w in ben if w["day"] == "Mon"]
    assert mon == [{"day": "Mon", "start": "19:00", "end": "21:00"}]  # clinicals 7-19 (hard)
    assert "Fri" not in {w["day"] for w in ben}  # Friday off (soft): just absent, no reason given
    assert all(set(w) == {"day", "start", "end"} for w in ben)

    ana = [w for w in agents["ana"].free_windows() if w["day"] == "Tue"]
    assert ana == [{"day": "Tue", "start": "09:00", "end": "12:00"},
                   {"day": "Tue", "start": "18:00", "end": "21:00"}]

    maya = agents["maya"].free_windows()
    assert all(w["end"] <= "18:00" for w in maya)


def test_private_decisions_match_the_scenario(agents):
    ana, ben, maya = agents["ana"], agents["ben"], agents["maya"]
    assert ben.evaluate(["PHIL215-01"]).hard            # Monday clinicals
    assert ana.evaluate(["PHIL215-02"]).hard            # Tue/Thu work
    assert [p.kind for p in ana.evaluate(["PHIL215-03"]).soft] == ["no_before"]
    assert [p.kind for p in ben.evaluate(["PHIL215-04"]).soft] == ["day_off"]
    assert ana.evaluate(["PHIL215-04"]).ok and maya.evaluate(["PHIL215-04"]).ok


def test_relaxing_a_pref_flips_decline_to_accept_and_widens_windows(agents):
    ben = agents["ben"]
    proposal = agents["ana"].propose("PHIL215-04")
    assert ben.respond(proposal).type is MessageType.DECLINE
    ben.relax(ben.active_prefs()[0])
    assert ben.respond(proposal).type is MessageType.ACCEPT
    assert "Fri" in {w["day"] for w in ben.free_windows()}
