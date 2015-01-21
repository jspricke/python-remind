# Python library to convert between Remind and iCalendar
#
# Copyright (C) 2013-2015  Jochen Sprickerhof
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

from codecs import open as copen
from datetime import date, datetime, timedelta
from dateutil import rrule
from dateutil.tz import gettz
from hashlib import sha1
from os.path import getmtime, expanduser
from socket import getfqdn
from subprocess import Popen, PIPE
from threading import Lock
from vobject import readOne, iCalendar


class Remind(object):

    def __init__(self, localtz, filename=expanduser('~/.reminders'),
                 startdate=date.today()-timedelta(weeks=12), month=15):
        self._localtz = localtz
        self._filename = filename
        self._startdate = startdate
        self._month = month
        self._lock = Lock()
        self._icals = {}
        self._mtime = 0

    def _parse_remind(self, filename, lines=''):
        cmd = ['remind', '-l', '-s%d' % self._month, '-b1', '-r', filename, str(self._startdate)]
        rem = Popen(cmd, stdin=PIPE, stdout=PIPE).communicate(input=lines.encode('utf-8'))[0].decode('utf-8')

        if len(rem) == 0:
            return {}

        events = {}
        files = {}
        for line in rem.split('\n#'):
            line = line.replace('\n', ' ').rstrip().split(' ')

            src_filename = line[3]

            if src_filename not in files:
                if lines:
                    files[src_filename] = lines.split('\n')
                else:
                    files[src_filename] = copen(src_filename, encoding='utf-8').readlines()
                events[src_filename] = {}
            text = files[src_filename][int(line[2])-1]

            event = self._parse_remind_line(line, text)

            if event['uid'] in events[src_filename]:
                events[src_filename][event['uid']]['dtstart'] += event['dtstart']
            else:
                events[src_filename][event['uid']] = event

        icals = {}
        for filename in events:
            icals[filename] = iCalendar()
            for event in events[filename].values():
                Remind._gen_vevent(event, icals[filename].add('vevent'))
        return icals

    @staticmethod
    def _gen_description(text):
        return text[text.rfind('%"') + 3:].replace('%_', '\n').replace('["["]', '[').strip()

    @staticmethod
    def _gen_uid(line_number, text):
        hashed_text = sha1(text.encode('utf-8')).hexdigest()
        return '%s-%s@%s' % (line_number, hashed_text, getfqdn())

    def _parse_remind_line(self, line, text):
        event = {}
        dat = [int(f) for f in line[4].split('/')]
        if line[8] != '*':
            start = divmod(int(line[8]), 60)
            event['dtstart'] = [datetime(dat[0], dat[1], dat[2], start[0], start[1], tzinfo=self._localtz)]
            if line[7] != '*':
                event['duration'] = timedelta(minutes=int(line[7]))
        else:
            event['dtstart'] = [date(dat[0], dat[1], dat[2])]

        msg = ' '.join(line[9:] if line[8] == '*' else line[10:])
        if ' at ' in msg:
            (event['msg'], event['location']) = msg.rsplit(' at ', 1)
        else:
            event['msg'] = msg

        if '%"' in text:
            event['description'] = Remind._gen_description(text)

        event['uid'] = Remind._gen_uid(line[2], text)

        return event

    @staticmethod
    def _weekly(dates):
        last = dates[0]
        for dat in dates[1:]:
            if (dat - last).days != 7:
                return False
            last = dat
        return True

    @staticmethod
    def _gen_dtend_rrule(dtstarts, vevent):
        if (max(dtstarts) - min(dtstarts)).days == len(dtstarts) - 1:
            if isinstance(dtstarts[0], datetime):
                rset = rrule.rruleset()
                rset.rrule(rrule.rrule(freq=rrule.DAILY, count=len(dtstarts)))
                vevent.rruleset = rset
            else:
                vevent.add('dtend').value = dtstarts[-1] + timedelta(days=1)
        elif Remind._weekly(dtstarts):
            rset = rrule.rruleset()
            rset.rrule(rrule.rrule(freq=rrule.WEEKLY, count=len(dtstarts)))
            vevent.rruleset = rset
        else:
            rset = rrule.rruleset()
            if isinstance(dtstarts[0], datetime):
                for dat in dtstarts:
                    # Workaround for a bug in Davdroid
                    # ignore the time zone information for rdates
                    # https://github.com/rfc2822/davdroid/issues/340
                    rset.rdate(dat.astimezone(gettz('UTC')))
            else:
                for dat in dtstarts:
                    rset.rdate(datetime(dat.year, dat.month, dat.day))
            # temporary set dtstart to a different date, so it's not
            # removed from rset by python-vobject works around bug in
            # Android:
            # https://github.com/rfc2822/davdroid/issues/340
            vevent.dtstart.value = dtstarts[0] - timedelta(days=1)
            vevent.rruleset = rset
            vevent.dtstart.value = dtstarts[0]
            if not isinstance(dtstarts[0], datetime):
                vevent.add('dtend').value = dtstarts[0] + timedelta(days=1)

    @staticmethod
    def _gen_vevent(event, vevent):
        vevent.add('dtstart').value = event['dtstart'][0]
        vevent.add('summary').value = event['msg']
        vevent.add('uid').value = event['uid']

        if 'location' in event:
            vevent.add('location').value = event['location']

        if 'description' in event:
            vevent.add('description').value = event['description']

        if isinstance(event['dtstart'][0], datetime):
            valarm = vevent.add('valarm')
            valarm.add('trigger').value = timedelta(minutes=-10)
            valarm.add('action').value = 'DISPLAY'
            valarm.add('description').value = event['msg']

            if 'duration' in event:
                vevent.add('duration').value = event['duration']
            else:
                vevent.add('dtend').value = event['dtstart'][0]

        elif len(event['dtstart']) == 1:
            vevent.add('dtend').value = event['dtstart'][0] + timedelta(days=1)

        if len(event['dtstart']) > 1:
            Remind._gen_dtend_rrule(event['dtstart'], vevent)

    def _update(self):
        update = not self._icals

        for fname in self._icals:
            mtime = getmtime(fname)
            if mtime > self._mtime:
                self._mtime = mtime
                update = True

        if update:
            self._lock.acquire()
            self._icals = self._parse_remind(self._filename)
            self._lock.release()

    def get_filesnames(self):
        self._update()
        return self._icals.keys()

    def to_vobject(self, filename):
        self._update()
        return self._icals.get(filename, iCalendar())

    def stdin_to_vobject(self, lines):
        return self._parse_remind('-', lines).get('-')

    def to_vobject_combined(self, filename):
        ccal = iCalendar()
        for cal in self._parse_remind(filename).values():
            for event in cal.components():
                ccal.add(event)
        return ccal

    @staticmethod
    def _parse_rruleset(rruleset):
        rep = []

        if rruleset._rrule[0]._byweekday and len(rruleset._rrule[0]._byweekday) > 1:
            rep.append('*1')
        elif rruleset._rrule[0]._freq == rrule.DAILY:
            rep.append('*1')
        elif rruleset._rrule[0]._freq == rrule.WEEKLY:
            rep.append('*7')
        # TODO MONTHLY, ..
        else:
            raise NotImplementedError

        if rruleset._rrule[0]._byweekday and len(rruleset._rrule[0]._byweekday) > 1:
            daynums = set(range(7)) - set(rruleset._rrule[0]._byweekday)
            weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            days = [weekdays[day] for day in daynums]
            rep.append('SKIP OMIT %s' % ' '.join(days))

        if rruleset._rrule[0]._until:
            rep.append(rruleset._rrule[0]._until.strftime('UNTIL %b %d %Y').replace(' 0', ' '))
        elif rruleset._rrule[0]._count:
            rep.append(rruleset[-1].strftime('UNTIL %b %d %Y').replace(' 0', ' '))

        return rep

    @staticmethod
    def _event_duration(event):
        if hasattr(event, 'dtend'):
            return event.dtend.value - event.dtstart.value
        elif hasattr(event, 'duration') and event.duration.value:
            return event.duration.value
        return timedelta(0)

    @staticmethod
    def _gen_msg(event, label):
        rem = ['MSG']
        msg = []
        if label:
            msg.append(label)
        msg.append(event.summary.value.replace('[', '["["]'))

        if hasattr(event, 'location') and event.location.value:
            msg.append('at %s' % event.location.value)

        if hasattr(event, 'description') and event.description.value:
            rem.append('%%"%s%%"' % ' '.join(msg))
            rem.append(event.description.value.replace('\n', '%_').replace('[', '["["]'))
        else:
            rem.append(' '.join(msg))

        return rem

    def to_remind(self, event, label=None, priority=None):
        remind = ['REM']

        if not hasattr(event, 'rdate'):
            remind.append(event.dtstart.value.strftime('%b %d %Y').replace(' 0', ' '))

        if priority:
            remind.append('PRIORITY %s' % priority)

        if hasattr(event, 'rrule') and event.rruleset._rrule[0]._freq != 0:
            remind.extend(Remind._parse_rruleset(event.rruleset))

        duration = Remind._event_duration(event)

        if type(event.dtstart.value) is date and duration.days > 1:
            remind.append('*1')
            if hasattr(event, 'dtend'):
                event.dtend.value -= timedelta(days=1)
                remind.append(event.dtend.value.strftime('UNTIL %b %d %Y').replace(' 0', ' '))

        if isinstance(event.dtstart.value, datetime):
            remind.append(event.dtstart.value.astimezone(self._localtz).strftime('AT %H:%M').replace(' 0', ' '))
            if duration.total_seconds() > 0:
                remind.append('DURATION %d:%02d' % divmod(duration.total_seconds() / 60, 60))

        if hasattr(event, 'rdate'):
            rdates = []
            for rdate in event.rdate.value:
                rdates.append(rdate.strftime("trigdate()=='%Y-%m-%d'"))
            remind.append('SATISFY [%s]' % '||'.join(rdates))

        remind.extend(Remind._gen_msg(event, label))

        return ' '.join(remind) + '\n'

    def to_reminds(self, ical, label=None, priority=None):
        reminders = []
        for event in ical.vevent_list:
            reminders.append(self.to_remind(event, label, priority))
        return ''.join(reminders)

    def append(self, ical, filename):
        if filename not in self._icals:
            return
        self._lock.acquire()
        copen(filename, 'a', encoding='utf-8').write(self.to_reminds(readOne(ical)))
        self._lock.release()

    def remove(self, name, filename):
        if filename not in self._icals:
            return
        uid = name.split('@')[0].split('-')
        if len(uid) != 2:
            return
        line = int(uid[0]) - 1
        self._lock.acquire()
        rem = copen(filename, encoding='utf-8').readlines()
        linehash = sha1(rem[line].encode('utf-8')).hexdigest()
        if linehash == uid[1]:
            del rem[line]
            copen(filename, 'w', encoding='utf-8').writelines(rem)
        self._lock.release()

    def replace(self, name, ical, filename):
        if filename not in self._icals:
            return
        uid = name.split('@')[0].split('-')
        if len(uid) != 2:
            return
        line = int(uid[0]) - 1
        self._lock.acquire()
        rem = copen(filename, encoding='utf-8').readlines()
        linehash = sha1(rem[line].encode('utf-8')).hexdigest()
        if linehash == uid[1]:
            rem[line] = self.to_reminds(readOne(ical))
            copen(filename, 'w', encoding='utf-8').writelines(rem)
        self._lock.release()


def rem2ics():
    from argparse import ArgumentParser, FileType
    from dateutil.parser import parse
    from sys import stdin, stdout

    parser = ArgumentParser(description='Converter from Remind to iCalendar syntax.')
    parser.add_argument('-s', '--startdate', type=lambda s: parse(s).date(),
                        default=date.today(), help='Start offset for remind call')
    parser.add_argument('-m', '--month', type=int, default=15,
                        help='Number of manth to generate calendar beginning wit stadtdate (default: 15)')
    parser.add_argument('-z', '--zone', default='Europe/Berlin',
                        help='Timezone of Remind file (default: Europe/Berlin)')
    parser.add_argument('infile', nargs='?', default=expanduser('~/.reminders'),
                        help='The Remind file to process (default: ~/.reminders)')
    parser.add_argument('outfile', nargs='?', type=FileType('w'), default=stdout,
                        help='Output iCalendar file (default: stdout)')
    args = parser.parse_args()

    zone = gettz(args.zone)
    # Manually set timezone name to generate correct ical files
    # (python-vobject tests for the zone attribute)
    zone.zone = args.zone

    if args.infile == '-':
        remind = Remind(zone, args.infile, startdate=args.startdate, month=args.month)
        vobject = remind.stdin_to_vobject(stdin.read().decode('utf-8'))
        if vobject:
            args.outfile.write(vobject.serialize())
    else:
        remind = Remind(zone, startdate=args.startdate, month=args.month)
        args.outfile.write(remind.to_vobject_combined(args.infile).serialize())


def ics2rem():
    from argparse import ArgumentParser, FileType
    from sys import stdin, stdout

    parser = ArgumentParser(description='Converter from iCalendar to Remind syntax.')
    parser.add_argument('-l', '--label', help='Label for every Remind entry')
    parser.add_argument('-p', '--priority', type=int,
                        help='Priority for every Remind entry (0..9999)')
    parser.add_argument('-z', '--zone', default='Europe/Berlin',
                        help='Timezone of Remind file (default: Europe/Berlin)')
    parser.add_argument('infile', nargs='?', type=FileType('r'), default=stdin,
                        help='Input iCalendar file (default: stdin)')
    parser.add_argument('outfile', nargs='?', type=FileType('w'), default=stdout,
                        help='Output Remind file (default: stdout)')
    args = parser.parse_args()

    zone = gettz(args.zone)
    # Manually set timezone name to generate correct ical files
    # (python-vobject tests for the zone attribute)
    zone.zone = args.zone

    vobject = readOne(args.infile.read().decode('utf-8'))
    rem = Remind(zone).to_reminds(vobject, args.label, args.priority)
    args.outfile.write(rem.encode('utf-8'))
