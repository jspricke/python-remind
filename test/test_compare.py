# Unit tests for ics_compare.py
#
# Copyright (C) 2014-2021  Jochen Sprickerhof
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime, timedelta

from dateutil import rrule
from vobject import iCalendar

from ics_compare import compare


def test_compare_simple() -> None:
    first = iCalendar()
    first.add("vevent")

    second = iCalendar()
    second.add("vevent")

    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 0
    assert len(second_out.contents) == 0


def test_compare_vevent_summary() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("summary").value = "Foo"

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("summary").value = "Foo"
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 0
    assert len(second_out.contents) == 0


def test_compare_summary_diff1() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("summary").value = "Foo"

    second = iCalendar()
    second.add("vevent")
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 1
    assert len(second_out.contents) == 1


def test_compare_summary_diff2() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("summary").value = "Foo"

    second = iCalendar()
    second.add("vevent")
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 1
    assert len(second_out.contents) == 1


def test_compare_summary_diff3() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("summary").value = "Foo"

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("summary").value = "Bar"
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 1
    assert len(second_out.contents) == 1


def test_compare_dtend() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    first_vevent.add("dtend").value = datetime(2001, 1, 1, 11, 0)

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    second_vevent.add("dtend").value = datetime(2001, 1, 1, 11, 0)
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 0
    assert len(second_out.contents) == 0


def test_compare_dtend_duration() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    first_vevent.add("dtend").value = datetime(2001, 1, 1, 11, 0)

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    second_vevent.add("duration").value = timedelta(hours=1)
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 0
    assert len(second_out.contents) == 0


def test_compare_dtend_duration_diff() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    first_vevent.add("dtend").value = datetime(2001, 1, 1, 11, 0)

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    second_vevent.add("duration").value = timedelta(hours=2)
    second_out = iCalendar()

    compare(first, second, second_out)
    assert len(first.contents) == 1
    assert len(second_out.contents) == 1


def test_compare_rrule() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    rset = rrule.rruleset()
    rset.rrule(rrule.rrule(freq=rrule.DAILY, count=3))
    first_vevent.rruleset = rset

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    second_out = iCalendar()
    rset = rrule.rruleset()
    rset.rrule(rrule.rrule(freq=rrule.DAILY, count=3))
    second_vevent.rruleset = rset

    compare(first, second, second_out)
    assert len(first.contents) == 0
    assert len(second_out.contents) == 0


def test_compare_rrule_diff() -> None:
    first = iCalendar()
    first_vevent = first.add("vevent")
    first_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    rset = rrule.rruleset()
    rset.rrule(rrule.rrule(freq=rrule.DAILY, count=3))
    first_vevent.rruleset = rset

    second = iCalendar()
    second_vevent = second.add("vevent")
    second_vevent.add("dtstart").value = datetime(2001, 1, 1, 10, 0)
    second_out = iCalendar()
    rset = rrule.rruleset()
    rset.rrule(rrule.rrule(freq=rrule.DAILY, count=4))
    second_vevent.rruleset = rset

    compare(first, second, second_out)
    assert len(first.contents) == 1
    assert len(second_out.contents) == 1
