"""Swap finder: unlock a full section with a multi-way seat swap.

Graph: an edge X -> Y means "X would accept the seat Y holds". A cycle through our
student (the seeker) is a swap where everyone gets a seat they want. Breadth-first
search finds the SHORTEST such cycle, so a 2-way swap beats a 3-way one.

Every participant must confirm: each seat holder gets a SWAP_OFFER describing its
part of the trade and answers ACCEPT or DECLINE. One decline drops that holder and
the search runs again.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from bus import MessageBus
from models import Message, MessageType, SeatHolder, Section

MAX_CYCLE = 5


@dataclass(frozen=True)
class Trade:
    giver: str
    section_id: str
    receiver: str

    def __str__(self) -> str:
        return f"{self.giver} gives {self.section_id} to {self.receiver}"


@dataclass(frozen=True)
class SwapCycle:
    trades: tuple[Trade, ...]

    @property
    def size(self) -> int:
        return len(self.trades)

    @property
    def participants(self) -> list[str]:
        return [t.giver for t in self.trades]

    def receives(self, who: str) -> str:
        return next(t.section_id for t in self.trades if t.receiver == who)

    def gives(self, who: str) -> str:
        return next(t.section_id for t in self.trades if t.giver == who)


def find_cycle(seeker: str, gives: list[str], wants: str, holders: list[SeatHolder],
               max_size: int = MAX_CYCLE) -> SwapCycle | None:
    """Shortest swap that gets `seeker` into `wants` by giving away one of `gives`."""
    if not gives:
        return None
    holders = sorted(holders, key=lambda h: h.id)
    by_section: dict[str, list[SeatHolder]] = defaultdict(list)
    for h in holders:
        if h.id != seeker:
            by_section[h.holds].append(h)

    start = by_section.get(wants, [])
    queue = deque([h] for h in start)
    seen = {h.id for h in start}
    while queue:
        path = queue.popleft()
        last = path[-1]
        give = next((g for g in gives if g in last.would_accept), None)
        if give is not None:
            return _cycle(seeker, give, path)
        if len(path) + 1 >= max_size:
            continue
        for sid in last.would_accept:
            for nxt in by_section.get(sid, []):
                if nxt.id not in seen:
                    seen.add(nxt.id)
                    queue.append(path + [nxt])
    return None


def _cycle(seeker: str, give: str, path: list[SeatHolder]) -> SwapCycle:
    """path = [h1..hk]: h1 gives to seeker, h2 gives to h1, ..., seeker gives to hk."""
    trades = [Trade(path[0].id, path[0].holds, seeker)]
    for prev, h in zip(path, path[1:]):
        trades.append(Trade(h.id, h.holds, prev.id))
    trades.append(Trade(seeker, give, path[-1].id))
    return SwapCycle(tuple(trades))


class SeatHolderAgent:
    """Agent for a mock student outside the group. Accepts a swap only if it matches what they want."""

    def __init__(self, holder: SeatHolder, willing: bool = True):
        self.holder = holder
        self.willing = willing

    @property
    def id(self) -> str:
        return self.holder.id

    def handle(self, msg: Message) -> Message | None:
        if msg.type is not MessageType.SWAP_OFFER:
            return None
        gives, gets = msg.payload["give_section"], msg.payload["want_section"]
        ok = self.willing and gives == self.holder.holds and gets in self.holder.would_accept
        type = MessageType.ACCEPT if ok else MessageType.DECLINE
        return Message(self.id, msg.sender, type, {"section_id": gets}, msg.round)


@dataclass
class SeatPlan:
    section_id: str
    open_seats: list[str] = field(default_factory=list)       # friends taking a free seat
    already_in: list[str] = field(default_factory=list)       # friends who already hold a seat
    swaps: dict[str, SwapCycle] = field(default_factory=dict)  # friend -> confirmed swap
    stuck: list[str] = field(default_factory=list)            # friends with no seat and no swap

    @property
    def ok(self) -> bool:
        return not self.stuck


def secure_seats(agents, section: Section, holders: list[SeatHolder], bus: MessageBus,
                 unwilling: frozenset[str] = frozenset(), round: int = 0) -> SeatPlan:
    """Get every friend into `section`: free seats first, then confirmed swaps."""
    plan = SeatPlan(section.id)
    holder_agents = {h.id: SeatHolderAgent(h, h.id not in unwilling) for h in holders}
    for hid in holder_agents:
        if not bus.has(hid):
            bus.register(hid)

    need = [a for a in agents if not a.holds(section.id)]
    plan.already_in = [a.id for a in agents if a.holds(section.id)]
    # Friends with nothing to trade take the free seats first.
    need.sort(key=lambda a: (bool(a.tradeable_seats(section.id)), a.id))
    free = section.seats_left
    used: set[str] = set()
    for a in need:
        if free > 0:
            plan.open_seats.append(a.id)
            free -= 1
            continue
        cycle = _confirmed_swap(a, section.id, holder_agents, used, bus, round)
        if cycle is None:
            plan.stuck.append(a.id)
        else:
            plan.swaps[a.id] = cycle
            used.update(cycle.participants)
    return plan


def _confirmed_swap(agent, want: str, holder_agents: dict[str, SeatHolderAgent],
                    used: set[str], bus: MessageBus, round: int) -> SwapCycle | None:
    gives = agent.tradeable_seats(want)
    excluded = set(used)
    while True:
        pool = [h.holder for hid, h in holder_agents.items() if hid not in excluded]
        cycle = find_cycle(agent.id, gives, want, pool)
        if cycle is None:
            return None
        others = [p for p in cycle.participants if p != agent.id]
        for p in others:
            bus.send(agent.swap_offer(cycle.gives(p), cycle.receives(p), p, round=round))
        for p in others:
            for msg in bus.receive(p):
                reply = holder_agents[p].handle(msg)
                if reply is not None:
                    bus.send(reply)
        replies = {m.sender: m.type for m in bus.receive(agent.id) if m.sender in others}
        decliners = [p for p in others if replies.get(p) is not MessageType.ACCEPT]
        if not decliners:
            return cycle
        excluded.update(decliners)
