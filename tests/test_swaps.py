"""Swap finder: 2-way, 3-way, no swap, and the confirm-or-retry flow."""

from dataclasses import replace

import pytest

from agent import Agent
from bus import MessageBus
from loader import load_scenario
from models import MessageType, SeatHolder
from swaps import find_cycle, secure_seats


def h(hid, holds, *wants):
    return SeatHolder(hid, hid.title(), holds, tuple(wants))


def trades(cycle):
    return [str(t) for t in cycle.trades]


# ---- the graph search ------------------------------------------------------

def test_two_way_swap():
    cycle = find_cycle("me", ["MINE"], "WANT", [h("x", "WANT", "MINE")])
    assert cycle.size == 2
    assert trades(cycle) == ["x gives WANT to me", "me gives MINE to x"]


def test_three_way_swap():
    holders = [h("x", "WANT", "B"), h("y", "B", "MINE")]
    cycle = find_cycle("me", ["MINE"], "WANT", holders)
    assert cycle.size == 3
    assert trades(cycle) == ["x gives WANT to me", "y gives B to x", "me gives MINE to y"]
    # Everyone ends up with something they asked for.
    assert cycle.receives("x") == "B" and cycle.receives("y") == "MINE"


def test_no_swap_possible():
    holders = [h("x", "WANT", "B"), h("y", "B", "C")]  # nobody wants MINE
    assert find_cycle("me", ["MINE"], "WANT", holders) is None
    assert find_cycle("me", [], "WANT", [h("x", "WANT", "MINE")]) is None
    assert find_cycle("me", ["MINE"], "NOBODY_HOLDS_THIS", holders) is None


def test_shortest_cycle_wins():
    holders = [h("a", "WANT", "B"), h("b", "B", "MINE"), h("c", "WANT", "MINE")]
    assert find_cycle("me", ["MINE"], "WANT", holders).participants == ["c", "me"]


def test_respects_max_size():
    holders = [h("a", "WANT", "B"), h("b", "B", "C"), h("c", "C", "MINE")]
    assert find_cycle("me", ["MINE"], "WANT", holders).size == 4
    assert find_cycle("me", ["MINE"], "WANT", holders, max_size=3) is None


def test_seeker_can_offer_any_of_several_seats():
    cycle = find_cycle("me", ["M1", "M2"], "WANT", [h("x", "WANT", "M2")])
    assert cycle.gives("me") == "M2"


def test_ignores_dead_ends_and_is_deterministic():
    holders = [h("dead", "WANT", "NOWHERE"), h("x", "WANT", "B"), h("y", "B", "MINE")]
    results = [trades(find_cycle("me", ["MINE"], "WANT", list(reversed(holders)))) for _ in range(3)]
    assert results[0] == ["x gives WANT to me", "y gives B to x", "me gives MINE to y"]
    assert all(r == results[0] for r in results)


# ---- the full flow on the real scenario ------------------------------------

@pytest.fixture
def setup():
    sc = load_scenario()
    agents = [Agent(st, sc.catalog, sc.sections) for st in sc.students.values()]
    ben = next(a for a in agents if a.id == "ben")
    ben.relax(ben.active_prefs()[0])  # the outcome negotiation reaches
    bus = MessageBus()
    for a in agents:
        bus.register(a.id)
    return sc, agents, bus


def test_scenario_three_way_swap_gets_ana_in(setup):
    sc, agents, bus = setup
    plan = secure_seats(agents, sc.sections["PHIL215-04"], list(sc.seat_holders.values()), bus)
    assert plan.ok and plan.open_seats == ["ben", "maya"]
    assert trades(plan.swaps["ana"]) == [
        "priya gives PHIL215-04 to ana",
        "quinn gives BIO240-02 to priya",
        "ana gives MATH220-01 to quinn",
    ]
    log = [(e.sender, e.recipient, e.type) for e in bus.log]
    assert log == [("ana", "priya", "SWAP_OFFER"), ("ana", "quinn", "SWAP_OFFER"),
                   ("priya", "ana", "ACCEPT"), ("quinn", "ana", "ACCEPT")]


def test_swap_offer_tells_each_holder_only_their_part(setup):
    sc, agents, bus = setup
    secure_seats(agents, sc.sections["PHIL215-04"], list(sc.seat_holders.values()), bus)
    offers = {e.recipient: e.payload for e in bus.log if e.type == "SWAP_OFFER"}
    assert offers["priya"] == {"give_section": "PHIL215-04", "want_section": "BIO240-02"}
    assert offers["quinn"] == {"give_section": "BIO240-02", "want_section": "MATH220-01"}


def test_a_decline_drops_that_holder_and_retries(setup):
    sc, agents, bus = setup
    # A second route: Zoe also holds a PHIL215-04 seat and wants Ana's MATH220-01 directly.
    holders = [*sc.seat_holders.values(), h("zoe", "PHIL215-04", "MATH220-01")]
    plan = secure_seats(agents, sc.sections["PHIL215-04"], holders, bus, unwilling=frozenset({"zoe"}))
    # Zoe's 2-way swap is tried first (shortest), she declines, the 3-way swap goes through.
    assert plan.ok and plan.swaps["ana"].size == 3
    assert ("zoe", "ana", "DECLINE") in [(e.sender, e.recipient, e.type) for e in bus.log]


def test_stuck_when_nobody_will_trade(setup):
    sc, agents, bus = setup
    plan = secure_seats(agents, sc.sections["PHIL215-04"], list(sc.seat_holders.values()), bus,
                        unwilling=frozenset({"priya"}))
    assert not plan.ok and plan.stuck == ["ana"]


def test_no_swap_when_there_are_enough_seats(setup):
    sc, agents, bus = setup
    roomy = replace(sc.sections["PHIL215-04"], seats_left=3)
    plan = secure_seats(agents, roomy, list(sc.seat_holders.values()), bus)
    assert plan.ok and plan.swaps == {} and sorted(plan.open_seats) == ["ana", "ben", "maya"]
    assert not any(e.type == MessageType.SWAP_OFFER.value for e in bus.log)
