# Co-Register

Hackathon project (DevHacks Fall '26, Cubbie Hackathon Track 2: Agent-to-Agent Coordination).
Friends' personal AI agents plan next semester together: they find classes that count for everyone (even across
different majors), line up schedules, resolve full sections with multi-way seat swaps, and ask each student to
confirm before anything is final.

## The scenario we demo
Three friends with different majors want at least one class together next semester:
- Ana, Computer Science. Works Tue/Thu afternoons. Hates 8 AM classes.
- Ben, Nursing. Clinicals Monday all day. Wants Fridays off.
- Maya, Business. Commutes, wants classes on as few days as possible.
Each still needs some general education categories (for example a humanities credit or a lab science).
Their agents must:
1. Find courses that satisfy an open requirement for ALL three, despite different majors.
2. Pick sections that fit everyone's hard constraints, scoring soft preferences.
3. Relax soft preferences in a fixed order when no section fits everyone, and say what was relaxed.
4. When the best section is full, find a multi-way swap with other (mock) students who hold seats.
5. Ask each student to confirm. Nothing is final until all three say yes; one "no" triggers a re-plan.

## What Track 2 judges look for (keep the demo aligned)
1. A working prototype tied to a real campus scenario.
2. How agents handle CONFLICTING constraints.
3. WHAT each agent shares and what it keeps private.
4. WHEN agents ask their student to confirm.
5. A clear reason students would say "we need this".

## Hard rules for how you work with me
- I am learning this stack. Before writing a file, say in 2-3 lines what it does and why. After each milestone,
  summarize in 5 lines what I should now understand.
- Plan first. For each milestone, propose the plan and wait for my OK before writing code.
- Keep it small. Python standard library plus what is listed below. No extra frameworks.
- Commit after each milestone with a clear message. Never commit secrets.
- Free only. No paid APIs. Everything must run offline with the LLM turned off.
- API keys live in `.env` (in `.gitignore`). Never print or hard-code a key.
- Write tests for the course finder, the schedule solver and the swap finder. They must be reliable.

## Stack
- Python 3.11+, `dataclasses`, `pytest`
- Optional: Google Gemini free tier (`google-genai`), only to PHRASE messages and explain outcomes
- Human confirmation: terminal prompt. A small web page is a stretch goal.

## Data (all mock, in `data/`)
- `catalog.json`: courses with sections (days, start/end times, seats left) and tags for which requirement
  categories each course satisfies (gen-ed categories and major requirements).
- `students.json`: the three friends, each with PRIVATE data: open requirements, busy blocks (work, clinicals),
  hard constraints, soft preferences with priorities.
- `seat_holders.json`: other mock students who hold seats in full sections and what they would rather have.

## Share policy (the privacy story)
An agent may share: which requirement CATEGORIES are still open, free time windows, and accept/decline on a
proposal. It never shares: GPA, full transcript, the reason it declined, job or clinical details, or which
preferences are soft vs hard. Log every message with the fields it contained so the demo can prove this.

## Design
- `models.py`: Course, Section, Student, TimeBlock, Preference, Message.
- `agent.py`: Agent with private state and the share policy. Builds outgoing messages only through the policy.
- `bus.py`: structured messages (PROPOSE, COUNTER, ACCEPT, DECLINE, SWAP_OFFER, ESCALATE_TO_HUMAN) and a log.
- `course_finder.py`: courses whose tags cover an open requirement for every student (set intersection).
- `solver.py`: picks sections for the shared course plus each student's other classes. Backtracking over
  sections, rejecting hard-constraint violations, scoring soft preferences.
- `negotiation.py`: rounds of propose/counter between agents; relaxes the lowest-priority soft preference across
  agents when nothing fits; escalates to humans when still stuck.
- `swaps.py`: builds a directed graph "student X would give seat A for seat B" and finds a cycle that gets our
  student into the full section (multi-way swap). Every participant must confirm.
- `phrasing.py`: optional LLM wording with a template fallback. The LLM never decides anything.
- `ics.py`: calendar file for each student's final schedule.
- `run_demo.py`: runs the scenario end to end with a clean, readable log.

## Milestones (build in this order)
1. Models and mock data loading.
2. Agent plus share policy, with a test proving private fields never appear in messages.
3. Message bus and log.
4. Course finder across different majors. Tests.
5. Schedule solver (hard constraints, soft scoring). Tests.
6. Negotiation rounds with relaxation and escalation.
7. Swap finder for full sections. Tests: 2-way swap, 3-way swap, no swap possible.
8. Human confirmation in the terminal, including re-plan on a "no".
9. Phrasing layer with fallback, `.ics` output, and `run_demo.py`.
10. README: one-paragraph pitch, how to run, a walkthrough of the conflict and the 3-way swap.
11. OPTIONAL, only if time is left: Team Contract. The same three agents, now in their shared class, split a
    group project by skills and other deadlines, and re-plan when someone falls behind.

## Definition of done
`python run_demo.py` runs offline and shows: a shared class found across three majors, a scheduling conflict
resolved with a stated relaxation, a full section unlocked by a 3-way swap, what each agent shared, each student
confirming, and calendar files written. Tests pass.
