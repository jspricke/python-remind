#!/usr/bin/env python3
#
# Python tool to compare two iCalendar files (specifically for python-remind)
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

from argparse import ArgumentParser
from datetime import datetime

from vobject import iCalendar
from vobject.base import Component, readComponents


def compare(first_in: Component, second_in: Component, second_out: Component) -> None:
    for (j, second) in enumerate(second_in.vevent_list):
        found = False
        for (i, first) in enumerate(first_in.vevent_list):
            wrong = False
            for attr in (
                "summary",
                "location",
                "description",
                "recurrence_id",
            ):
                if (
                    hasattr(first, attr)
                    and first.contents.get(attr)
                    and first.contents.get(attr)[0].value
                    and not (
                        hasattr(second, attr)
                        and second.contents.get(attr)
                        and second.contents.get(attr)[0].value
                        and first.contents.get(attr)[0].value
                        == second.contents.get(attr)[0].value
                    )
                ):
                    wrong = True
                    break

            # ignore timezone when comparing dates (not supported by remind)
            if hasattr(first, "dtstart") and not (
                hasattr(second, "dtstart")
                and (
                    (
                        isinstance(first.dtstart.value, datetime)
                        and isinstance(second.dtstart.value, datetime)
                        and first.dtstart.value.timestamp()
                        == second.dtstart.value.timestamp()
                    )
                    or first.dtstart.value == second.dtstart.value
                )
            ):
                wrong = True

            if hasattr(first, "dtend"):
                if hasattr(second, "dtend") and (
                    (
                        isinstance(first.dtend.value, datetime)
                        and isinstance(second.dtend.value, datetime)
                        and first.dtend.value.timestamp()
                        != second.dtend.value.timestamp()
                    )
                    or first.dtend.value != second.dtend.value
                ):
                    wrong = True
                elif (
                    hasattr(second, "duration")
                    and first.dtend.value
                    != second.dtstart.value + second.duration.value
                ):
                    wrong = True
                elif not (hasattr(second, "dtend") or hasattr(second, "duration")):
                    wrong = True

            if hasattr(first, "duration"):
                if (
                    hasattr(second, "duration")
                    and first.duration.value != second.duration.value
                ):
                    wrong = True
                elif (
                    hasattr(second, "dtend")
                    and first.duration.value
                    != second.dtend.value - second.dtstart.value
                ):
                    wrong = True
                elif not (hasattr(second, "dtend") or hasattr(second, "duration")):
                    wrong = True

            if hasattr(first, "rruleset") and first.rruleset:
                if (
                    hasattr(second, "rruleset")
                    and second.rruleset
                    and list(first.rruleset) != list(second.rruleset)
                ):
                    wrong = True
                elif (
                    hasattr(second, "rdate")
                    and second.rdate.value
                    and list(first.rruleset) != second.rdate.value
                ):
                    wrong = True
                elif not (hasattr(second, "rruleset") or hasattr(second, "rdate")):
                    wrong = True

            if hasattr(first, "rdate") and first.rdate.value:
                if (
                    hasattr(second, "rdate")
                    and second.rdate.value
                    and first.rdate.value != second.rdate.value
                ):
                    wrong = True
                elif (
                    hasattr(second, "rruleset")
                    and second.rruleset
                    and first.rdate.value != list(second.rruleset)
                ):
                    wrong = True
                elif not (hasattr(second, "rruleset") or hasattr(second, "rdate")):
                    wrong = True

            if wrong:
                continue

            found = True
            first_in.remove(first)
            print(f"matching {i} to {j}")
        if not found:
            second_out.add(second)


def main() -> None:
    parser = ArgumentParser(description="Compare two iCalendar files semantically")
    parser.add_argument("first_input", help="First iCalendar file input")
    parser.add_argument("second_input", help="Second iCalendar file input")
    parser.add_argument("first_output", help="First iCalendar file output")
    parser.add_argument("second_output", help="Second iCalendar file output")
    args = parser.parse_args()
    with open(args.first_input, encoding="utf-8") as infile:
        first_cal = next(readComponents(infile))
    with open(args.second_input, encoding="utf-8") as infile:
        second_cal = next(readComponents(infile))
    second_out = iCalendar()

    compare(first_cal, second_cal, second_out)

    with open(args.first_output, "w", encoding="utf-8") as outfile:
        outfile.write(first_cal.serialize())
    with open(args.second_output, "w", encoding="utf-8") as outfile:
        outfile.write(second_out.serialize())


if __name__ == "__main__":
    main()
