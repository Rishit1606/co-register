"""Write each student's final schedule as an .ics calendar file (Spring 2027, weekly repeats).

Plain RFC 5545 text: one VEVENT per section-and-time, repeating weekly on its days
until the semester ends. Times are "floating" local time, so no time-zone setup is needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from models import DAYS, Course, Section, format_time

SEMESTER_START = date(2027, 1, 19)  # Tuesday
SEMESTER_END = date(2027, 5, 7)
STAMP = "20261024T000000Z"          # fixed, so output is reproducible
ICS_DAYS = {"Mon": "MO", "Tue": "TU", "Wed": "WE", "Thu": "TH", "Fri": "FR"}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def _first_date(days: list[str], start: date) -> date:
    wanted = {DAYS.index(d) for d in days}
    d = start
    while d.weekday() not in wanted:
        d += timedelta(days=1)
    return d


def _hhmm(minutes: int) -> str:
    return format_time(minutes).replace(":", "") + "00"


def calendar(owner: str, sections: list[Section], catalog: dict[str, Course],
             start: date = SEMESTER_START, end: date = SEMESTER_END) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Co-Register//Demo//EN",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_escape(owner)} - Spring 2027"]
    until = end.strftime("%Y%m%d") + "T235959"
    for s in sections:
        course = catalog[s.course_id]
        groups: dict[tuple, list[str]] = {}
        for m in s.meetings:
            groups.setdefault((m.start, m.end, m.label), []).append(m.day)
        for (m_start, m_end, label), days in groups.items():
            first = _first_date(days, start).strftime("%Y%m%d")
            kind = f" ({label})" if label and label != "Lecture" else ""
            lines += [
                "BEGIN:VEVENT",
                f"UID:{owner.lower()}-{s.id}-{''.join(ICS_DAYS[d] for d in days)}-{m_start}@co-register",
                f"DTSTAMP:{STAMP}",
                f"DTSTART:{first}T{_hhmm(m_start)}",
                f"DTEND:{first}T{_hhmm(m_end)}",
                f"RRULE:FREQ=WEEKLY;UNTIL={until};BYDAY={','.join(ICS_DAYS[d] for d in days)}",
                f"SUMMARY:{_escape(f'{course.id} {course.title}{kind}')}",
                f"DESCRIPTION:{_escape(f'Section {s.id}, {course.credits} credits')}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def write_calendar(path: Path, owner: str, sections: list[Section], catalog: dict[str, Course]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(calendar(owner, sections, catalog), encoding="utf-8", newline="")
    return path
