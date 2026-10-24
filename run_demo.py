"""Co-Register demo: three friends' agents plan next semester together.

    python3 run_demo.py                     # everyone says yes (scripted), fully offline
    python3 run_demo.py --answers y,n,y,y,y # Ben says no once -> re-plan
    python3 run_demo.py --interactive       # type each student's answer yourself
    python3 run_demo.py --llm               # reword public summary lines with Gemini (needs .env key)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bus import MessageBus
from confirm import names_of, plan_and_confirm
from ics import write_calendar
from loader import load_scenario
from phrasing import Phraser, join_names, narrate

OUT = Path(__file__).parent / "out"
WIDTH = 78

PHASES = {
    "share": "1. Each agent shares only what the policy allows",
    "find": "2. Find a class that counts for all three majors",
    "negotiate": "3. Negotiate a section (conflicting constraints)",
    "seats": "4. Get everyone a seat",
    "confirm": "5. Each student confirms (nothing is final until all say yes)",
    "calendar": "6. Calendar files",
    "privacy": "7. Privacy audit: what crossed the bus",
}


class Narrator:
    def __init__(self):
        self.current = None

    def phase(self, key: str) -> None:
        if key != self.current:
            self.current = key
            print(f"\n{'=' * WIDTH}\n{PHASES[key]}\n{'=' * WIDTH}")

    def on_message(self, entry, names, sections) -> None:
        kind = entry.type
        if kind == "SHARE":
            self.phase("share")
        elif kind in ("PROPOSE", "COUNTER", "RELAX", "ESCALATE_TO_HUMAN"):
            self.phase("negotiate")
        elif kind == "SWAP_OFFER":
            self.phase("seats")
        line = narrate(entry, names, sections)
        if line:
            print(line)

    def say(self, text: str) -> None:
        if self.current == "share":
            self.phase("find")
        if text.lstrip().startswith("--- Private to"):
            self.phase("confirm")
        elif self.current == "negotiate" and "take the open seats" in text:
            self.phase("seats")
        print(text)


def _rel(path: Path) -> Path:
    return path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path


def scripted(answers: list[str]):
    it = iter(answers)

    def ask(prompt: str) -> str:
        answer = next(it, "y")
        print(prompt + answer)
        return answer
    return ask


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", default="", help="comma-separated y/n answers, in order asked")
    parser.add_argument("--interactive", action="store_true", help="type each answer in the terminal")
    parser.add_argument("--llm", action="store_true", help="reword public summary lines with Gemini")
    args = parser.parse_args(argv)

    sc = load_scenario()
    names = names_of(sc)
    phraser = Phraser.from_env(args.llm)
    narrator = Narrator()
    bus = MessageBus(listener=lambda e: narrator.on_message(e, names, sc.sections))

    friends = [f"{s.name} ({s.major})" for s in sc.students.values()]
    print(f"Co-Register: {join_names(friends)} want at least one class together next semester.")
    print("Each agent holds its student's private data: GPA, transcript, work/clinical schedule,")
    print("and preferences with how much each one matters. Watch what actually crosses the bus.")
    print(f"Wording: {'Gemini (public summary lines only, facts checked)' if phraser.uses_llm else 'templates (offline)'}")

    ask = input if args.interactive else scripted([a.strip() for a in args.answers.split(",") if a.strip()])
    result = plan_and_confirm(sc, bus, ask=ask, say=narrator.say, phraser=phraser)

    if result.status != "confirmed":
        print(f"\nResult: {result.status}. No schedule is final; the students decide together.")
    else:
        narrator.phase("calendar")
        for sid, sched in result.schedules.items():
            student = sc.students[sid]
            sections = [sc.sections[x] for x in sched.section_ids]
            path = write_calendar(OUT / f"{sid}.ics", student.name, sections, sc.catalog)
            print(f"{student.name:<5} -> {_rel(path)}  ({', '.join(sched.section_ids)})")

    narrator.phase("privacy")
    log_path = bus.save(OUT / "message_log.json")
    audit = bus.audit()
    for st in sc.students.values():
        print(f"{st.name}'s agent shared only: {', '.join(audit[st.id])}")
    print("Never shared: GPA, transcript, job/clinical details, why it declined, "
          "which preferences are soft vs hard, what it relaxed.")
    text = json.dumps([e.payload for e in bus.log]).lower()
    secrets = [v for st in sc.students.values()
               for v in [str(st.gpa), *st.transcript, *(b.label for b in st.busy_blocks)]]
    leaks = [s for s in secrets if s.lower() in text]
    print(f"Scanned all {len(bus.log)} messages for {len(secrets)} private values: {len(leaks)} found.")
    print(f"Full message log: {_rel(log_path)}")
    if result.rejected:
        print("Re-plans: " + ", ".join(f"{sid} ({names.get(who, who)} said no)" if who != "no seat"
                                       else f"{sid} (no seat)" for sid, who in result.rejected))
    return 0 if not leaks else 1


if __name__ == "__main__":
    raise SystemExit(main())
