# Python library to convert between Remind and iCalendar
#
# Copyright (C) 2013-2018  Jochen Sprickerhof
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
from hashlib import md5
from os.path import expanduser, getmtime, isfile
from pytz import timezone
from socket import getfqdn
from subprocess import Popen, PIPE
from time import time
from threading import Lock
from tzlocal import get_localzone
from vobject import readOne, iCalendar


class Remind(object):
    """Represents a collection of Remind files"""

    def __init__(self, filename=expanduser('~/.reminders'), localtz=None,
                 startdate=date.today() - timedelta(weeks=12), month=15,
                 alarm=timedelta(minutes=-10)):
        """Constructor

        filename -- the remind file (included files will be used as well)
        localtz -- the timezone of the remind file
        startdate -- the date to start parsing, will be passed to remind
        month -- how many month to parse, will be passed to remind -s
        """
        self._localtz = localtz if localtz else get_localzone()
        self._filename = filename
        self._startdate = startdate
        self._month = month
        self._lock = Lock()
        self._reminders = {}
        self._mtime = 0
        self._alarm = alarm
        self._update()

    def _parse_remind(self, filename, lines=''):
        """Calls remind and parses the output into a dict

        filename -- the remind file (included files will be used as well)
        lines -- used as stdin to remind (filename will be set to -)
        """
        files = {}
        reminders = {}
        if lines:
            filename = '-'
            files[filename] = lines.split('\n')
            reminders[filename] = {}

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
            if src_filename not in files:
                # There is a race condition with the remind call above here.
                # This could be solved by parsing the remind -de output,
                # but I don't see an easy way to do that.
                files[src_filename] = open(src_filename).readlines()
                reminders[src_filename] = {}
                mtime = getmtime(src_filename)
                if mtime > self._mtime:
                    self._mtime = mtime

            text = files[src_filename][int(fileinfo[2]) - 1]
            event = self._parse_remind_line(line, text)
            if event['uid'] in reminders[src_filename]:
                reminders[src_filename][event['uid']]['dtstart'] += event['dtstart']
                reminders[src_filename][event['uid']]['line'] += line
            else:
                reminders[src_filename][event['uid']] = event
                reminders[src_filename][event['uid']]['line'] = line

        # Find included files without reminders and add them to the file list
        for source in files.values():
            for line in source:
                if line.startswith('include'):
                    new_file = line.split(' ')[1].strip()
                    if new_file not in reminders and isfile(new_file):
                        reminders[new_file] = {}
                        mtime = getmtime(new_file)
                        if mtime > self._mtime:
                            self._mtime = mtime

        return reminders

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

        event['uid'] = Remind._get_uid(text)

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
            rset.rrule(rrule.rrule(freq=rrule.WEEKLY, interval=interval // 7, count=len(dtstarts)))
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
        vevent.add('dtstamp').value = datetime.fromtimestamp(self._mtime)
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
        update = not self._reminders

        now = time()
        if datetime.fromtimestamp(self._mtime).date() < datetime.fromtimestamp(now).date():
            update = True
            self._mtime = now

        with self._lock:
            for fname in self._reminders:
                if getmtime(fname) > self._mtime:
                    update = True
                    break

            if update:
                self._reminders = self._parse_remind(self._filename)

    def get_filesnames(self):
        """All filenames parsed by remind (including included files)"""
        self._update()
        return list(self._reminders.keys())

    @staticmethod
    def _get_uid(line):
        """UID of a remind line"""
        return '%s@%s' % (md5(line.strip().encode('utf-8')).hexdigest(), getfqdn())

    def get_uids(self, filename=None):
        """UIDs of all reminders in the file excluding included files
        If a filename is specified, only it's UIDs are return, otherwise all.

        filename -- the remind file
        """
        self._update()

        if filename:
            if filename not in self._reminders:
                return []
            return self._reminders[filename].keys()
        return [uid for uids in self._reminders.values() for uid in uids]

    def to_vobject_etag(self, filename, uid):
        """Return iCal object and etag of one Remind entry

        filename -- the remind file
        uid -- the UID of the Remind line
        """
        return self.to_vobjects(filename, [uid])[0][1:3]

    def to_vobjects(self, filename, uids=None):
        """Return iCal objects and etags of all Remind entries in uids

        filename -- the remind file
        uids -- the UIDs of the Remind lines (all if None)
        """
        self._update()

        if not uids:
            uids = self._reminders[filename]

        items = []

        for uid in uids:
            cal = iCalendar()
            self._gen_vevent(self._reminders[filename][uid], cal.add('vevent'))
            items.append((uid, cal, '"%s"' % uid.split('@')[0]))
        return items

    def to_vobject(self, filename=None, uid=None):
        """Return iCal object of Remind lines
        If filename and UID are specified, the vObject only contains that event.
        If only a filename is specified, the vObject contains all events in the file.
        Otherwise the vObject contains all all objects of all files associated with the Remind object.

        filename -- the remind file
        uid -- the UID of the Remind line
        """
        self._update()

        cal = iCalendar()
        if uid:
            self._gen_vevent(self._reminders[filename][uid], cal.add('vevent'))
        elif filename:
            for event in self._reminders[filename].values():
                self._gen_vevent(event, cal.add('vevent'))
        else:
            for filename in self._reminders:
                for event in self._reminders[filename].values():
                    self._gen_vevent(event, cal.add('vevent'))
        return cal

    def stdin_to_vobject(self, lines):
        """Return iCal object of the Remind commands in lines"""
        cal = iCalendar()
        for event in self._parse_remind('-', lines)['-'].values():
            self._gen_vevent(event, cal.add('vevent'))
        return cal

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
            rep.append('*%d' % (7 * rruleset._rrule[0]._interval))
        elif rruleset._rrule[0]._freq == rrule.MONTHLY:
            rep.append('%d' % rruleset._rrule[0]._bymonthday[0])
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
    def _gen_msg(vevent, label, tail, sep):
        """Generate a Remind MSG from the given vevent.
        Opposite of _gen_description()
        """
        rem = ['MSG']
        msg = []
        if label:
            msg.append(label)

        if hasattr(vevent, 'summary') and vevent.summary.value:
            msg.append(Remind._rem_clean(vevent.summary.value))
        else:
            msg.append('empty reminder')

        if hasattr(vevent, 'location') and vevent.location.value:
            msg.append('at %s' % Remind._rem_clean(vevent.location.value))

        has_desc = hasattr(vevent, 'description') and vevent.description.value

        if tail or has_desc:
            rem.append('%%"%s%%"' % ' '.join(msg))
        else:
            rem.append(' '.join(msg))

        if tail:
            rem.append(tail)

        if has_desc:
            rem[-1] += sep + Remind._rem_clean(vevent.description.value)

        return ' '.join(rem)

    @staticmethod
    def _rem_clean(rem):
        """Strip, transform newlines, and escape '[' in string so it's
        acceptable as a remind entry."""
        return rem.strip().replace('%', '%%').replace('\n', '%_').replace('[', '["["]')

    @staticmethod
    def _abbr_tag(tag):
        """Transform a string so it's acceptable as a remind tag. """
        return tag.replace(" ", "")[:48]

    def to_remind(self, vevent, label=None, priority=None, tags=None, tail=None,
                  sep=" ", postdate=None, posttime=None):
        """Generate a Remind command from the given vevent"""
        remind = ['REM']

        trigdates = None
        if hasattr(vevent, 'rrule'):
            trigdates = Remind._parse_rruleset(vevent.rruleset)

        dtstart = vevent.dtstart.value
        # If we don't get timezone information, handle it as a naive datetime.
        # See https://github.com/jspricke/python-remind/issues/2 for reference.
        if isinstance(dtstart, datetime) and dtstart.tzinfo:
            dtstart = dtstart.astimezone(self._localtz)

        dtend = None
        if hasattr(vevent, 'dtend'):
            dtend = vevent.dtend.value
        if isinstance(dtend, datetime) and dtend.tzinfo:
            dtend = dtend.astimezone(self._localtz)

        if not hasattr(vevent, 'rdate') and not isinstance(trigdates, str) and (not hasattr(vevent, 'rrule') or vevent.rruleset._rrule[0]._freq != rrule.MONTHLY):
            remind.append(dtstart.strftime('%b %d %Y').replace(' 0', ' '))

        if postdate:
            remind.append(postdate)

        if priority:
            remind.append('PRIORITY %s' % priority)

        if isinstance(trigdates, list):
            remind.extend(trigdates)

        duration = Remind._event_duration(vevent)

        if type(dtstart) is date and duration.days > 1:
            remind.append('*1')
            if dtend is not None:
                dtend -= timedelta(days=1)
                remind.append(dtend.strftime('UNTIL %b %d %Y').replace(' 0', ' '))

        if isinstance(dtstart, datetime):
            remind.append(dtstart.strftime('AT %H:%M').replace(' 0', ' '))

            if posttime:
                remind.append(posttime)

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

        remind.append(Remind._gen_msg(vevent, label, tail, sep))

        return ' '.join(remind) + '\n'

    def to_reminders(self, ical, label=None, priority=None, tags=None,
                     tail=None, sep=" ", postdate=None, posttime=None):
        """Return Remind commands for all events of a iCalendar"""
        if not hasattr(ical, 'vevent_list'):
            return ''

        reminders = [self.to_remind(vevent, label, priority, tags, tail, sep,
                                    postdate, posttime)
                     for vevent in ical.vevent_list]
        return ''.join(reminders)

    def append(self, ical, filename=None):
        """Append a Remind command generated from the iCalendar to the file"""
        return self.append_vobject(readOne(ical), filename)

    def append_vobject(self, ical, filename=None):
        """Append a Remind command generated from the iCalendar to the file"""
        if not filename:
            filename = self._filename
        elif filename not in self._reminders:
            return

        with self._lock:
            outdat = self.to_reminders(ical)
            open(filename, 'a').write(outdat)

        return Remind._get_uid(outdat)

    def remove(self, uid, filename=None):
        """Remove the Remind command with the uid from the file"""
        if not filename:
            filename = self._filename
        elif filename not in self._reminders:
            return

        uid = uid.split('@')[0]

        with self._lock:
            rem = open(filename).readlines()
            for (index, line) in enumerate(rem):
                if uid == md5(line.strip().encode('utf-8')).hexdigest():
                    del rem[index]
                    open(filename, 'w').writelines(rem)
                    break

    def replace(self, uid, ical, filename=None):
        """Update the Remind command with the uid in the file with the new iCalendar"""
        return self.replace_vobject(uid, readOne(ical), filename)

    def replace_vobject(self, uid, ical, filename=None):
        """Update the Remind command with the uid in the file with the new iCalendar"""
        if not filename:
            filename = self._filename
        elif filename not in self._reminders:
            return

        uid = uid.split('@')[0]

        with self._lock:
            rem = open(filename).readlines()
            for (index, line) in enumerate(rem):
                if uid == md5(line.strip().encode('utf-8')).hexdigest():
                    rem[index] = self.to_reminders(ical)
                    new_uid = self._get_uid(rem[index])
                    open(filename, 'w').writelines(rem)
                    return new_uid

    def move_vobject(self, uid, from_file, to_file):
        """Move the Remind command with the uid from from_file to to_file"""
        if from_file not in self._reminders or to_file not in self._reminders:
            return

        uid = uid.split('@')[0]

        with self._lock:
            rem = open(from_file).readlines()
            for (index, line) in enumerate(rem):
                if uid == md5(line.strip().encode('utf-8')).hexdigest():
                    del rem[index]
                    open(from_file, 'w').writelines(rem)
                    open(to_file, 'a').write(line)
                    break

    def get_meta(self):
        """Meta tags of the vObject collection"""
        return {'tag': 'VCALENDAR', 'C:supported-calendar-component-set': 'VEVENT'}

    def last_modified(self):
        """Last time the Remind files where parsed"""
        self._update()
        return self._mtime


def rem2ics():
    """Command line tool to convert from Remind to iCalendar"""
    # pylint: disable=maybe-no-member
    from argparse import ArgumentParser, FileType
    from dateutil.parser import parse
    from sys import stdin, stdout

    parser = ArgumentParser(description='Converter from Remind to iCalendar syntax.')
    parser.add_argument('-s', '--startdate', type=lambda s: parse(s).date(),
                        default=date.today() - timedelta(weeks=12),
                        help='Start offset for remind call (default: -12 weeks)')
    parser.add_argument('-m', '--month', type=int, default=15,
                        help='Number of month to generate calendar beginning wit startdate (default: 15)')
    parser.add_argument('-a', '--alarm', type=int, default=-10,
                        help='Trigger time for the alarm before the event in minutes (default: -10)')
    parser.add_argument('-z', '--zone',
                        help='Timezone of Remind file (default: local timezone)')
    parser.add_argument('infile', nargs='?', default=expanduser('~/.reminders'),
                        help='The Remind file to process (default: ~/.reminders)')
    parser.add_argument('outfile', nargs='?', type=FileType('w'), default=stdout,
                        help='Output iCalendar file (default: stdout)')
    args = parser.parse_args()

    zone = timezone(args.zone) if args.zone else None

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
    parser.add_argument('--tail',
                        help='Text to append to every remind summary, following final %%"')
    parser.add_argument('--sep', default=" ",
                        help='String to separate summary (and tail) from description')
    parser.add_argument('--postdate',
                        help='String to follow the date in every Remind entry. '
                        'Useful for entering "back" and "delta" fields (see man remind).')
    parser.add_argument('--posttime',
                        help='String to follow the time in every timed Remind entry. '
                        'Useful for entering "tdelta" and "trepeat" fields (see man remind).')
    parser.add_argument('-z', '--zone',
                        help='Timezone of Remind file (default: local timezone)')
    parser.add_argument('infile', nargs='?', type=FileType('r'), default=stdin,
                        help='Input iCalendar file (default: stdin)')
    parser.add_argument('outfile', nargs='?', type=FileType('w'), default=stdout,
                        help='Output Remind file (default: stdout)')
    args = parser.parse_args()

    zone = timezone(args.zone) if args.zone else None

    vobject = readOne(args.infile.read())
    rem = Remind(localtz=zone).to_reminders(
        vobject, args.label, args.priority, args.tag, args.tail, args.sep,
        args.postdate, args.posttime)
    args.outfile.write(rem)
