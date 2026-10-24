# Co-Register

*DevHacks Fall '26 · Cubbie Hackathon Track 2: Agent-to-Agent Coordination*

Getting into a class with your friends is hard when you're in different majors. Each of you
has different requirements, a different job or clinical schedule, and a different idea of
what a good week looks like. Usually it takes a group chat, three degree audits, and someone
giving up. **Co-Register** gives each student a personal agent. The agents find a class that
counts for *everyone*, negotiate a section around conflicting constraints, relax the least
important preferences when nothing fits, and get into full sections through multi-way seat
swaps. They do all this while sharing only what they have to: never your GPA, your
transcript, your job, or *why* you said no. Nothing is final until every student says yes.

## Run it

Python 3.11+, standard library only. Runs fully offline.

```bash
python3 run_demo.py                      # the full story; every student answers "yes"
python3 run_demo.py --answers y,n        # Ben says no -> the agents re-plan
python3 run_demo.py --interactive        # you type each student's answer
python3 confirm.py                       # just the confirmation loop, interactive

pip install pytest && python3 -m pytest  # 93 tests
```

The demo writes `out/ana.ics`, `out/ben.ics` and `out/maya.ics`, which you can import into
any calendar app, plus `out/message_log.json`, which holds every message that crossed the
bus.

**Optional:** `--llm` lets Gemini (free tier) reword a few *public* summary lines. To use it,
`pip install google-genai` and put `GEMINI_API_KEY=...` in `.env`. The LLM never decides
anything. If its wording drops or changes any course code, section, number or name, the
template text is used instead. Private briefings are never sent to it.

## The scenario

| | Major | Needs (private) | Constraints (private) |
|---|---|---|---|
| **Ana** | Computer Science | GEN_HUM, CS_CORE, CS_MATH | works Tue/Thu 12–6 · hates 8 AM classes |
| **Ben** | Nursing | NURS_ETHICS, LAB_SCI, NURS_CORE | clinicals all Monday · wants Fridays off |
| **Maya** | Business | BUS_ETHICS, BUS_CORE, GEN_QUANT | nothing after 6 PM · classes on ≤ 3 days |

Each agent knows which of its student's rules are **hard** (work, clinicals, credit limits)
and which are **soft** preferences with a priority. Nobody else does.

## Walkthrough

**1. Share.** Each agent broadcasts its open requirement *categories* and its *free time
windows*. Busy blocks, hard limits and soft preferences are merged into plain windows, so
Ben's Monday (clinicals, hard) and Ben's Friday (preference, soft) look the same: both are
simply not free.

**2. Find a class for three majors.** The course finder intersects each course's tags with
each student's shared categories. **PHIL215 Ethics in Technology, Health & Business** is the
only course that counts for all three, and it counts differently for each: GEN_HUM for Ana,
NURS_ETHICS for Ben, BUS_ETHICS for Maya. COMM220, HSCI230 and MATH220 are near misses that
each leave one friend out.

**3. The conflict.** PHIL215 has four sections, and none works for everyone:

| Section | Time | Problem |
|---|---|---|
| 01 | Mon/Wed 10:00 | Ben's clinicals *(hard)* |
| 02 | Tue/Thu 13:00 | Ana's job *(hard)* |
| 03 | Wed/Fri 8:00 | Ana's no-8 AM, Ben's Friday off, Maya's 3-day max *(soft)* |
| 04 | Wed/Fri 11:00 | Ben's Friday off *(soft)* · and only **2 seats left** for 3 friends |

The agents take turns proposing (Ana: 01, Ben: 02, Maya: 04), and each proposal is
declined *with no reason given*. Once nobody has anything left to propose, the lead agent
broadcasts `RELAX {level: 1}`. Every agent privately relaxes its own preferences of
priority 1. Only Ben has one: "Fridays off". The other agents never learn whose preference
it was or what it was. Agents then re-check the sections they turned down: Ben's agent
now accepts 04, sections someone still declines are never proposed again, and one more
proposal settles on **PHIL215-04**. Ben's private
briefing says exactly what Ben's agent gave up. The friends' briefings don't mention it.

Each agent's solver plans its student's whole week around the shared section (backtracking,
with hard rules rejecting a schedule and soft preferences costing points). So an agent
accepts only if it can build a complete schedule, not just fit that one class.

**4. The 3-way swap.** Section 04 has 2 seats and the group needs 3. Ben and Maya take the
open seats. Ana holds a seat in MATH220-01, which clashes with section 04, so Ana's plan moves
to MATH220-02 and the old seat becomes something Ana can trade. The swap finder builds a
graph of "who would accept whose seat" and does a breadth-first search for the *shortest*
cycle back to Ana:

```
Priya gives a PHIL215-04 seat to Ana       (Priya wants BIO240-02)
Quinn gives a BIO240-02 seat to Priya      (Quinn wants MATH220-01)
Ana gives a MATH220-01 seat to Quinn
```

Ana's agent sends Priya and Quinn each a `SWAP_OFFER` that describes only *their* part of
the trade, and both accept. If either had declined, the finder would drop them and search
again. Raj and Sam hold seats too, but their wants lead nowhere, so the search ignores them.

**5. Confirm.** Each student sees a private briefing: their full schedule, how they got
their seat, and what *their* agent relaxed. Then they answer y/n. A yes is broadcast as
`ACCEPT` and a no as `DECLINE`, with no reason. **One "no" re-plans:** with
`--answers y,n`, Ben turns down 04, the agents exclude it, reset all relaxations, and
negotiate again. They settle on section 03 at relaxation level 3, where all three give
something up and each is told only about their own.

**6. Calendars.** Each confirmed schedule is written as an `.ics` file with weekly
repeating events for Spring 2027.

## What agents share, and what they keep

| Shared on the bus | Never shared |
|---|---|
| open requirement **categories** | GPA, transcript |
| free time **windows** (no labels) | job and clinical details |
| proposals, accept / decline | *why* an agent declined |
| relaxation **level** | which preferences are soft vs hard, and their priorities |
| swap offers (which seat for which) | what an agent relaxed |

This is enforced in code, not by convention:
- Agents build every message through a `SharePolicy`. It checks each message type against a
  list of allowed fields, and scans the payload for that student's own private values.
- The bus checks the field list again.
- Every message is logged with the fields it carried.
- The demo ends by scanning the whole log for every private value. The result is 0.

`tests/test_share_policy.py` sends every kind of message each agent can produce and checks
that none of them leaks. Two honest caveats:
- After a `RELAX`, the others can infer that *someone* had a low-priority preference blocking
  agreement, though not who or what.
- A swap offer reveals which seat Ana holds, because you can't trade a seat without saying
  which one.

## When agents ask their student

- **Before anything is final:** every student confirms the complete plan.
- **When they're stuck:** if no section works even after every relaxation level, each agent
  escalates to its student with the best-supported options instead of choosing for them.
- **Never mid-negotiation:** agents handle proposals, counters, relaxation and swaps on their
  own. The student sees one clear decision, with the trade-offs their agent made.

## Project layout

| File | What it does |
|---|---|
| `models.py` | dataclasses: TimeBlock, Section, Course, Constraint, Preference, Student, SeatHolder, Message |
| `loader.py` | loads and validates `data/catalog.json`, `students.json`, `seat_holders.json` |
| `agent.py` | an Agent with private state; `SharePolicy` gates every outgoing message |
| `bus.py` | message bus: inboxes, log, audit, JSON export |
| `course_finder.py` | courses that cover an open category for every student |
| `solver.py` | per-student backtracking schedule solver (hard rules reject, soft preferences cost points) |
| `negotiation.py` | propose / counter rounds, privacy-preserving relaxation, escalation |
| `swaps.py` | shortest seat-swap cycle (breadth-first search) plus per-participant confirmation |
| `confirm.py` | private briefings, terminal y/n, re-plan on "no" |
| `phrasing.py` | templates, plus optional fact-checked LLM rewording |
| `ics.py` | calendar files |
| `run_demo.py` | the narrated end-to-end demo |

All data is mock. No paid APIs, and no network unless you pass `--llm`.
