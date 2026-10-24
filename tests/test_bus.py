"""Message bus: delivery, broadcast, logging, audit and export."""

import json

import pytest

from agent import Agent
from bus import BusError, MessageBus, human
from loader import load_scenario
from models import Message, MessageType


@pytest.fixture
def bus():
    b = MessageBus()
    for a in ("ana", "ben", "maya"):
        b.register(a)
    return b


def msg(sender, recipient, type=MessageType.PROPOSE, **payload):
    payload = payload or {"section_id": "PHIL215-04", "course_id": "PHIL215"}
    return Message(sender, recipient, type, payload, round=1)


def test_direct_message_reaches_only_recipient(bus):
    bus.send(msg("ana", "ben"))
    assert len(bus.receive("ben")) == 1
    assert bus.receive("maya") == [] and bus.receive("ana") == []


def test_broadcast_skips_sender_and_humans(bus):
    bus.send(msg("ana", "all"))
    assert len(bus.receive("ben")) == 1 and len(bus.receive("maya")) == 1
    assert bus.receive("ana") == [] and bus.receive(human("ben")) == []
    assert len(bus.log) == 1  # one message, logged once


def test_receive_clears_inbox(bus):
    bus.send(msg("ana", "ben"))
    bus.receive("ben")
    assert bus.receive("ben") == []


def test_escalation_lands_in_human_inbox(bus):
    m = msg("ana", human("ana"), MessageType.ESCALATE_TO_HUMAN, section_id="PHIL215-04", options=[])
    bus.send(m)
    assert bus.receive(human("ana")) == [m]


def test_log_records_fields_in_order(bus):
    bus.send(msg("ana", "all"))
    bus.send(msg("ben", "ana", MessageType.DECLINE, section_id="PHIL215-04"))
    first, second = bus.log
    assert (first.seq, first.sender, first.type, first.fields) == (1, "ana", "PROPOSE", ["course_id", "section_id"])
    assert (second.seq, second.recipient, second.fields) == (2, "ana", ["section_id"])
    assert "ben → ana" in bus.render() and "fields=[section_id]" in bus.render()


@pytest.mark.parametrize("bad", [
    msg("zoe", "ana"),                                                   # unknown sender
    msg("ana", "zoe"),                                                   # unknown recipient
    msg("ben", "ana", MessageType.DECLINE, section_id="X", reason="work"),  # field not allowed
])
def test_rejects_bad_messages(bus, bad):
    with pytest.raises(BusError):
        bus.send(bad)
    assert bus.log == []  # rejected messages are not logged


def test_audit_lists_fields_each_agent_shared(bus):
    bus.send(msg("ana", "all"))
    bus.send(msg("ben", "ana", MessageType.DECLINE, section_id="PHIL215-04"))
    assert bus.audit() == {"ana": ["course_id", "section_id"], "ben": ["section_id"], "maya": []}


def test_saved_log_from_real_agents_has_no_private_data(tmp_path):
    sc = load_scenario()
    bus = MessageBus()
    agents = {sid: Agent(st, sc.catalog, sc.sections) for sid, st in sc.students.items()}
    for a in agents.values():
        bus.register(a.id)
        bus.send(a.share_open_categories())
        bus.send(a.share_free_windows())
    proposal = agents["ana"].propose("PHIL215-04", round=1)
    bus.send(proposal)
    for a in ("ben", "maya"):
        for m in bus.receive(a):
            if m.type is MessageType.PROPOSE:
                bus.send(agents[a].respond(m))

    path = bus.save(tmp_path / "log.json")
    text = path.read_text().lower()
    data = json.loads(text)
    assert len(data["messages"]) == 9
    for st in sc.students.values():
        for secret in [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]:
            assert secret.lower() not in text
    assert data["shared_fields"]["ben"] == ["free_windows", "open_categories", "section_id"]
