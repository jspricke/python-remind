#!/usr/bin/env python
#
# Python tool to compare two iCalendar files (specifically for python-remind)
#
# Copyright (C) 2014-2015  Jochen Sprickerhof
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

from card_me import readComponents, iCalendar
from argparse import ArgumentParser


def compare(first_in, second_in, second_out):
    for (j, second) in enumerate(second_in.vevent_list):
        found = False
        for (i, first) in enumerate(first_in.vevent_list):
            wrong = False
            for attr in ['dtstart', 'summary', 'location' 'description', 'recurrence_id', 'rdate', 'rrule']:
                if hasattr(first, attr):
                    if hasattr(second, attr) and first.contents.get(attr)[0].value != second.contents.get(attr)[0].value:
                        wrong = True
                        break
                    if not hasattr(second, attr):
                        wrong = True
                        break

            if hasattr(first, 'dtend'):
                if hasattr(second, 'dtend') and first.dtend.value != second.dtend.value:
                    wrong = True
                elif hasattr(second, 'duration') and first.dtend.value != second.dtstart.value + second.duration.value:
                    wrong = True
                elif not (hasattr(second, 'dtend') or hasattr(second, 'duration')):
                    wrong = True

            if hasattr(first, 'duration'):
                if hasattr(second, 'duration') and first.duration.value != second.duration.value:
                    wrong = True
                elif hasattr(second, 'dtend') and first.duration.value != second.dtend.value - second.dtstart.value:
                    wrong = True
                elif not (hasattr(second, 'dtend') or hasattr(second, 'duration')):
                    wrong = True

            if wrong:
                continue

            found = True
            first_in.remove(first)
            print("matching %d to %d" % (i, j))
        if not found:
            second_out.add(second)


def main():
    parser = ArgumentParser(description='Compare two iCalendar files semantically')
    parser.add_argument('first_input', help='First iCalendar file input')
    parser.add_argument('second_input', help='Second iCalendar file input')
    parser.add_argument('first_output', help='First iCalendar file output')
    parser.add_argument('second_output', help='Second iCalendar file output')
    args = parser.parse_args()
    first_cal = next(readComponents(open(args.first_input)))
    second_cal = next(readComponents(open(args.second_input)))
    second_out = iCalendar()

    compare(first_cal, second_cal, second_out)

    open(args.first_output, 'w').write(first_cal.serialize())
    open(args.second_output, 'w').write(second_out.serialize())

if __name__ == '__main__':
    main()
