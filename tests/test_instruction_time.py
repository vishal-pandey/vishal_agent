"""The instruction must carry a FRESH, pre-resolved calendar on every request.

Two defects this guards against:

1. `instruction=_instruction_with_now(...)` was evaluated once at import, so a
   long-running pod told the model a start-up timestamp forever. A pod up for a
   week resolved "tomorrow" to a week ago.

2. The model was trained on booking dialogues whose dates all fell in
   2026-09-15..19 (build_data.py used a single `base` date), so it partially
   memorised that range and fell back to it -- a real booking asked for
   "tomorrow" landed on 2026-09-19. Handing it the resolved dates removes the
   arithmetic instead of asking it to redo it.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from vishal_agent.agent import build_instruction, root_agent


def test_instruction_is_a_provider_not_a_frozen_string():
    """A str instruction is baked in at import; a callable is evaluated per request."""
    assert callable(root_agent.instruction), (
        "instruction must be an InstructionProvider so the date is current on "
        "every request, not frozen at pod start"
    )


def test_instruction_time_is_current_not_import_time():
    now = datetime.now(timezone.utc)
    text = build_instruction()
    assert now.strftime("%d %B %Y") in text
    # the stated hour must be the real one, within a minute of now
    m = re.search(r"current date and time is [^,]+, (\d{2} \w+ \d{4}), (\d{2}):(\d{2}) UTC", text)
    assert m, f"could not find a timestamp in: {text[:200]!r}"
    stated = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}",
                               "%d %B %Y %H:%M").replace(tzinfo=timezone.utc)
    assert abs((now - stated).total_seconds()) < 120


def test_instruction_resolves_tomorrow_to_an_explicit_date():
    """'Tomorrow' must not require the model to do date arithmetic."""
    text = build_instruction()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    assert f"Tomorrow is" in text
    assert tomorrow in text


def test_instruction_lists_the_next_two_weeks_with_weekday_names():
    """'next Tuesday' and 'Thursday' must be lookups, not calculations."""
    text = build_instruction()
    now = datetime.now(timezone.utc)
    for offset in range(1, 15):
        d = now + timedelta(days=offset)
        assert d.strftime("%Y-%m-%d") in text, f"missing {d:%Y-%m-%d} from the date table"
        assert d.strftime("%A") in text


def test_instruction_marks_weekends_as_unbookable():
    """The calendar is Monday-Friday; a listed Saturday must say so."""
    text = build_instruction()
    now = datetime.now(timezone.utc)
    weekend = [now + timedelta(days=o) for o in range(1, 15)
               if (now + timedelta(days=o)).weekday() >= 5]
    assert weekend, "the next 14 days always contain a weekend"
    for d in weekend:
        line = next((l for l in text.splitlines() if d.strftime("%Y-%m-%d") in l), None)
        assert line is not None
        assert "no meetings" in line.lower() or "closed" in line.lower(), (
            f"weekend day {d:%Y-%m-%d} not marked unbookable: {line!r}"
        )


def test_instruction_still_carries_the_facts_and_the_working_window():
    text = build_instruction()
    assert "03:30-11:30" in text          # working hours in UTC
    assert "Asia/Kolkata" in text
    assert "Lumiq" in text                # the fact block survived
    assert "contact@vishalpandey.ai" in text
