"""In-memory message bus: delivers messages to inboxes and logs every one of them.

The log records which payload fields each message carried, so the demo can show
exactly what each agent shared. The bus re-checks the field whitelist as a second
layer, but it never sees private data, so it can't (and needn't) scan for it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agent import ALLOWED_FIELDS
from models import Message


class BusError(Exception):
    pass


@dataclass(frozen=True)
class LogEntry:
    seq: int
    round: int
    sender: str
    recipient: str
    type: str
    fields: list[str]
    payload: dict

    def line(self) -> str:
        values = "  ".join(f"{k}={_short(v)}" for k, v in self.payload.items())
        route = f"{self.sender} → {self.recipient}"
        return (f"#{self.seq:02d} r{self.round}  {route:<20} "
                f"{self.type:<17} fields=[{', '.join(self.fields)}]  {values}")


def _short(value) -> str:
    if isinstance(value, list):
        if len(value) > 4 or any(isinstance(v, dict) for v in value):
            return f"[{len(value)} items]"
        return "[" + ", ".join(map(str, value)) + "]"
    return str(value)


def human(agent_id: str) -> str:
    """Inbox id for the person an agent works for."""
    return f"human:{agent_id}"


class MessageBus:
    def __init__(self, listener=None):
        """`listener`, if given, is called with each LogEntry as it is sent (live narration)."""
        self._listener = listener
        self._agents: list[str] = []
        self._inboxes: dict[str, list[Message]] = {}
        self.log: list[LogEntry] = []

    def register(self, agent_id: str) -> None:
        if agent_id in self._inboxes:
            raise BusError(f"{agent_id!r} is already registered")
        self._agents.append(agent_id)
        self._inboxes[agent_id] = []
        self._inboxes[human(agent_id)] = []

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def send(self, msg: Message) -> None:
        if msg.sender not in self._agents:
            raise BusError(f"unknown sender {msg.sender!r}")
        if msg.recipient == "all":
            recipients = [a for a in self._agents if a != msg.sender]
        elif msg.recipient in self._inboxes:
            recipients = [msg.recipient]
        else:
            raise BusError(f"unknown recipient {msg.recipient!r}")
        extra = set(msg.payload) - ALLOWED_FIELDS[msg.type]
        if extra:
            raise BusError(f"{msg.type.value} may not carry field(s) {sorted(extra)}")

        entry = LogEntry(
            seq=len(self.log) + 1,
            round=msg.round,
            sender=msg.sender,
            recipient=msg.recipient,
            type=msg.type.value,
            fields=msg.field_names(),
            payload=dict(msg.payload),
        )
        self.log.append(entry)
        if self._listener is not None:
            self._listener(entry)
        for r in recipients:
            self._inboxes[r].append(msg)

    def receive(self, inbox_id: str) -> list[Message]:
        """Return and clear everything waiting in an inbox."""
        if inbox_id not in self._inboxes:
            raise BusError(f"unknown inbox {inbox_id!r}")
        msgs, self._inboxes[inbox_id] = self._inboxes[inbox_id], []
        return msgs

    def render(self) -> str:
        return "\n".join(e.line() for e in self.log)

    def audit(self) -> dict[str, list[str]]:
        """For each agent: every payload field it ever shared."""
        shared: dict[str, set[str]] = {a: set() for a in self._agents}
        for e in self.log:
            shared[e.sender].update(e.fields)
        return {a: sorted(f) for a, f in shared.items()}

    def save(self, path: Path = Path("out/message_log.json")) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": [asdict(e) for e in self.log], "shared_fields": self.audit()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
