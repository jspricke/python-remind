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
"""Python library to convert between Remind and iCalendar"""

from datetime import date, datetime, timedelta
from dateutil import rrule
from dateutil.tz import gettz
from hashlib import md5
from os.path import getmtime, expanduser
from socket import getfqdn
from subprocess import Popen, PIPE
from threading import Lock
from card_me import readOne, iCalendar


class Remind(object):
    """Represents a collection of Remind files"""

    def __init__(self, filename=expanduser('~/.reminders'), localtz=gettz(),
                 startdate=date.today()-timedelta(weeks=12), month=15,
                 alarm=timedelta(minutes=-10)):
        """Constructor

        filename -- the remind file (included files will be used as well)
        localtz -- the timezone of the remind file
        startdate -- the date to start parsing, will be passed to remind
        month -- how many month to parse, will be passed to remind -s
        """
        self._localtz = localtz
        self._filename = filename
        self._startdate = startdate
        self._month = month
        self._lock = Lock()
        self._icals = {}
        self._mtime = 0
        self._alarm = alarm

    @staticmethod
    def _load_files(files, filename, lines=''):
        """load content of Remind files and store it in the files dict
           recursively include all included files as well

        files -- dict mapping filenames to content
        filename -- file to parse
        lines -- used as stdin to remind (filename will be set to -)

        """
        if lines:
            files[filename] = (lines.split('\n'), {})
        else:
            files[filename] = (open(filename).readlines(), {})
        for line in files[filename][0]:
            if line.startswith('include'):
                Remind._load_files(files, line.split(' ')[1].strip())

    def _parse_remind(self, filename, lines=''):
        """Calls remind and parses the output into a dict

        filename -- the remind file (included files will be used as well)
        lines -- used as stdin to remind (filename will be set to -)
        """
        if lines:
            filename = '-'

        files = {}
        Remind._load_files(files, filename, lines)

        cmd = ['remind', '-l', '-s%d' % self._month, '-b1', '-y', '-r',
               filename, str(self._startdate)]
        try:
            rem = Popen(cmd, stdin=PIPE, stdout=PIPE).communicate(input=lines.encode('utf-8'))[0].decode('utf-8')
        except OSError:
            raise OSError('Error running: %s' % ' '.join(cmd))

        rem = rem.splitlines()
        for (fileinfo, line) in zip(rem[::2], rem[1::2]):
            fileinfo = fileinfo.split()
            src_filename = fileinfo[3]
            text = files[src_filename][0][int(fileinfo[2])-1]

            event = self._parse_remind_line(line, text)
            if event['uid'] in files[src_filename][1]:
                files[src_filename][1][event['uid']]['dtstart'] += event['dtstart']
            else:
                files[src_filename][1][event['uid']] = event

        icals = {}
        for filename in files:
            icals[filename] = iCalendar()
            for event in files[filename][1].values():
                self._gen_vevent(event, icals[filename].add('vevent'))
        return icals

    @staticmethod
    def _gen_description(text):
        """Convert from Remind MSG to iCal description
        Opposite of _gen_msg()
        """
        return text[text.rfind('%"') + 3:].replace('%_', '\n').replace('["["]', '[').strip()

    def _parse_remind_line(self, line, text):
        """Parse a line of remind output into a dict

        line -- the remind output
        text -- the original remind input
        """
        event = {}
        line = line.split(None, 6)
        dat = [int(f) for f in line[0].split('/')]
        if line[4] != '*':
            start = divmod(int(line[4]), 60)
            event['dtstart'] = [datetime(dat[0], dat[1], dat[2], start[0], start[1], tzinfo=self._localtz)]
            if line[3] != '*':
                event['duration'] = timedelta(minutes=int(line[3]))
        else:
            event['dtstart'] = [date(dat[0], dat[1], dat[2])]

        msg = ' '.join(line[5:]) if line[4] == '*' else line[6]
        msg = msg.strip().replace('%_', '\n').replace('["["]', '[')

        if ' at ' in msg:
            (event['msg'], event['location']) = msg.rsplit(' at ', 1)
        else:
            event['msg'] = msg

        if '%"' in text:
            event['description'] = Remind._gen_description(text)

        tags = line[2].split(',')

        classes = ['PUBLIC', 'PRIVATE', 'CONFIDENTIAL']

        for tag in tags[:-1]:
            if tag in classes:
                event['class'] = tag

        event['categories'] = [tag for tag in tags[:-1] if tag not in classes]

        event['uid'] = '%s@%s' % (tags[-1][7:], getfqdn())

        return event

    @staticmethod
    def _interval(dates):
        """Return the distance between all dates and 0 if they are different"""
        interval = (dates[1] - dates[0]).days
        last = dates[0]
        for dat in dates[1:]:
            if (dat - last).days != interval:
                return 0
            last = dat
        return interval

    @staticmethod
    def _gen_dtend_rrule(dtstarts, vevent):
        """Generate an rdate or rrule from a list of dates and add it to the vevent"""
        interval = Remind._interval(dtstarts)
        if interval > 0 and interval % 7 == 0:
            rset = rrule.rruleset()
            rset.rrule(rrule.rrule(freq=rrule.WEEKLY, interval=interval//7, count=len(dtstarts)))
            vevent.rruleset = rset
        elif interval > 1:
            rset = rrule.rruleset()
            rset.rrule(rrule.rrule(freq=rrule.DAILY, interval=interval, count=len(dtstarts)))
            vevent.rruleset = rset
        elif interval > 0:
            if isinstance(dtstarts[0], datetime):
                rset = rrule.rruleset()
                rset.rrule(rrule.rrule(freq=rrule.DAILY, count=len(dtstarts)))
                vevent.rruleset = rset
            else:
                vevent.add('dtend').value = dtstarts[-1] + timedelta(days=1)
        else:
            rset = rrule.rruleset()
            if isinstance(dtstarts[0], datetime):
                for dat in dtstarts:
                    rset.rdate(dat)
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

    def _gen_vevent(self, event, vevent):
        """Generate vevent from given event"""
        vevent.add('dtstart').value = event['dtstart'][0]
        vevent.add('summary').value = event['msg']
        vevent.add('uid').value = event['uid']

        if 'class' in event:
            vevent.add('class').value = event['class']

        if 'categories' in event and len(event['categories']) > 0:
            vevent.add('categories').value = event['categories']

        if 'location' in event:
            vevent.add('location').value = event['location']

        if 'description' in event:
            vevent.add('description').value = event['description']

        if isinstance(event['dtstart'][0], datetime):
            if self._alarm != timedelta():
                valarm = vevent.add('valarm')
                valarm.add('trigger').value = self._alarm
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
        """Reload Remind files if the mtime is newer"""
        update = not self._icals

        for fname in self._icals:
            mtime = getmtime(fname)
            if mtime > self._mtime:
                self._mtime = mtime
                update = True

        if update:
            with self._lock:
                self._icals = self._parse_remind(self._filename)

    def get_filesnames(self):
        """All filenames parsed by remind (including included files)"""
        self._update()
        return list(self._icals.keys())

    def get_uids(self):
        """UIDs of all reminders in the file excluding included files"""
        with self._lock:
            rem = open(self._filename).readlines()
            return ['%s@%s' % (md5(line[:-1].encode('utf-8')).hexdigest(), getfqdn()) for line in rem if line.startswith('REM')]

    def to_vobject(self, filename=None):
        """Return iCal object of all Remind files or the specified filename"""
        self._update()

        if filename:
            return self._icals[filename]

        if len(self._icals) == 1:
            return list(self._icals.values())[0]

        ccal = iCalendar()
        for cal in self._icals.values():
            for vevent in cal.components():
                ccal.add(vevent)
        return ccal

    def stdin_to_vobject(self, lines):
        """Return iCal object of the Remind commands in lines"""
        return self._parse_remind('-', lines).get('-')

    @staticmethod
    def _parse_rdate(rdates):
        """Convert from iCal rdate to Remind trigdate syntax"""
        trigdates = [rdate.strftime("trigdate()=='%Y-%m-%d'") for rdate in rdates]
        return 'SATISFY [%s]' % '||'.join(trigdates)

    @staticmethod
    def _parse_rruleset(rruleset):
        """Convert from iCal rrule to Remind recurrence syntax"""
        # pylint: disable=protected-access

        if rruleset._rrule[0]._freq == 0:
            return []

        rep = []
        if rruleset._rrule[0]._byweekday and len(rruleset._rrule[0]._byweekday) > 1:
            rep.append('*1')
        elif rruleset._rrule[0]._freq == rrule.DAILY:
            rep.append('*%d' % rruleset._rrule[0]._interval)
        elif rruleset._rrule[0]._freq == rrule.WEEKLY:
            rep.append('*%d' % (7*rruleset._rrule[0]._interval))
        else:
            return Remind._parse_rdate(rruleset._rrule[0])

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
    def _event_duration(vevent):
        """unify dtend and duration to the duration of the given vevent"""
        if hasattr(vevent, 'dtend'):
            return vevent.dtend.value - vevent.dtstart.value
        elif hasattr(vevent, 'duration') and vevent.duration.value:
            return vevent.duration.value
        return timedelta(0)

    @staticmethod
    def _gen_msg(vevent, label):
        """Generate a Remind MSG from the given vevent.
        Opposite of _gen_description()
        """
        rem = ['MSG']
        msg = []
        if label:
            msg.append(label)

        if hasattr(vevent, 'summary') and vevent.summary.value:
            msg.append(vevent.summary.value.strip())
        else:
            msg.append('empty reminder')

        if hasattr(vevent, 'location') and vevent.location.value:
            msg.append('at %s' % vevent.location.value.strip())

        if hasattr(vevent, 'description') and vevent.description.value:
            rem.append('%%"%s%%"' % ' '.join(msg))
            rem.append(vevent.description.value.strip())
        else:
            rem.append(' '.join(msg))

        return ' '.join(rem).replace('\n', '%_').replace('[', '["["]')

    @staticmethod
    def _abbr_tag(tag):
        """Transform a string so it's acceptable as a remind tag. """
        return tag.replace(" ", "")[:48]

    def to_remind(self, vevent, label=None, priority=None, tags=None):
        """Generate a Remind command from the given vevent"""
        remind = ['REM']

        trigdates = None
        if hasattr(vevent, 'rrule'):
            trigdates = Remind._parse_rruleset(vevent.rruleset)

        if not hasattr(vevent, 'rdate') and not isinstance(trigdates, str):
            remind.append(vevent.dtstart.value.strftime('%b %d %Y').replace(' 0', ' '))

        if priority:
            remind.append('PRIORITY %s' % priority)

        if isinstance(trigdates, list):
            remind.extend(trigdates)

        duration = Remind._event_duration(vevent)

        if type(vevent.dtstart.value) is date and duration.days > 1:
            remind.append('*1')
            if hasattr(vevent, 'dtend'):
                vevent.dtend.value -= timedelta(days=1)
                remind.append(vevent.dtend.value.strftime('UNTIL %b %d %Y').replace(' 0', ' '))

        if isinstance(vevent.dtstart.value, datetime):
            # If we don't get timezone information, handle it as a naive datetime.
            # See https://github.com/jspricke/python-remind/issues/2 for reference.
            if vevent.dtstart.value.tzinfo:
                remind.append(vevent.dtstart.value.astimezone(self._localtz).strftime('AT %H:%M').replace(' 0', ' '))
            else:
                remind.append(vevent.dtstart.value.strftime('AT %H:%M').replace(' 0', ' '))
            if duration.total_seconds() > 0:
                remind.append('DURATION %d:%02d' % divmod(duration.total_seconds() / 60, 60))

        if hasattr(vevent, 'rdate'):
            remind.append(Remind._parse_rdate(vevent.rdate.value))
        elif isinstance(trigdates, str):
            remind.append(trigdates)

        if hasattr(vevent, 'class'):
            remind.append('TAG %s' % Remind._abbr_tag(vevent.getChildValue('class')))

        if tags:
            remind.extend(['TAG %s' % Remind._abbr_tag(tag) for tag in tags])

        if hasattr(vevent, 'categories_list'):
            for categories in vevent.categories_list:
                for category in categories.value:
                    remind.append('TAG %s' % Remind._abbr_tag(category))

        remind.append(Remind._gen_msg(vevent, label))

        return ' '.join(remind) + '\n'

    def to_reminders(self, ical, label=None, priority=None, tags=None):
        """Return Remind commands for all events of a iCalendar"""
        if not hasattr(ical, 'vevent_list'):
            return ''

        reminders = [self.to_remind(vevent, label, priority, tags)
                        for vevent in ical.vevent_list]
        return ''.join(reminders)

    def append(self, ical, filename=None):
        """Append a Remind command generated from the iCalendar to the file"""
        if not filename:
            filename = self._filename
        elif filename not in self._icals:
            return

        with self._lock:
            outdat = self.to_reminders(readOne(ical))
            open(filename, 'a').write(outdat)

    def remove(self, uid, filename=None):
        """Remove the Remind command with the uid from the file"""
        if not filename:
            filename = self._filename
        elif filename not in self._icals:
            return

        uid = uid.split('@')[0]

        with self._lock:
            rem = open(filename).readlines()
            for (index, line) in enumerate(rem):
                if uid == md5(line[:-1].encode('utf-8')).hexdigest():
                    del rem[index]
                    open(filename, 'w').writelines(rem)
                    break

    def replace(self, uid, ical, filename=None):
        """Update the Remind command with the uid in the file with the new iCalendar"""
        if not filename:
            filename = self._filename
        elif filename not in self._icals:
            return

        uid = uid.split('@')[0]

        with self._lock:
            rem = open(filename).readlines()
            for (index, line) in enumerate(rem):
                if uid == md5(line[:-1].encode('utf-8')).hexdigest():
                    rem[index] = self.to_reminders(readOne(ical))
                    open(filename, 'w').writelines(rem)
                    break


def rem2ics():
    """Command line tool to convert from Remind to iCalendar"""
    # pylint: disable=maybe-no-member
    from argparse import ArgumentParser, FileType
    from dateutil.parser import parse
    from sys import stdin, stdout

    parser = ArgumentParser(description='Converter from Remind to iCalendar syntax.')
    parser.add_argument('-s', '--startdate', type=lambda s: parse(s).date(),
                        default=date.today()-timedelta(weeks=12),
                        help='Start offset for remind call (default: -12 weeks)')
    parser.add_argument('-m', '--month', type=int, default=15,
                        help='Number of month to generate calendar beginning wit stadtdate (default: 15)')
    parser.add_argument('-a', '--alarm', type=int, default=-10,
                        help='Trigger time for the alarm before the event in minutes (default: -10)')
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
        remind = Remind(args.infile, zone, args.startdate, args.month, timedelta(minutes=args.alarm))
        vobject = remind.stdin_to_vobject(stdin.read())
        if vobject:
            args.outfile.write(vobject.serialize())
    else:
        remind = Remind(args.infile, zone, args.startdate, args.month, timedelta(minutes=args.alarm))
        args.outfile.write(remind.to_vobject().serialize())


def ics2rem():
    """Command line tool to convert from iCalendar to Remind"""
    from argparse import ArgumentParser, FileType
    from sys import stdin, stdout

    parser = ArgumentParser(description='Converter from iCalendar to Remind syntax.')
    parser.add_argument('-l', '--label', help='Label for every Remind entry')
    parser.add_argument('-p', '--priority', type=int,
                        help='Priority for every Remind entry (0..9999)')
    parser.add_argument('-t', '--tag', action='append',
                        help='Tag(s) for every Remind entry')
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

    vobject = readOne(args.infile.read())
    rem = Remind(localtz=zone).to_reminders(
        vobject, args.label, args.priority, args.tag)
    args.outfile.write(rem)
