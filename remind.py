# Python library to convert between Remind and iCalendar
#
# Copyright (C) 2013-2024  Jochen Sprickerhof
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
"""Python library to convert between Remind and iCalendar."""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from hashlib import md5
from json import JSONDecodeError, loads
from os.path import expanduser, getmtime, isfile
from re import findall
from socket import getfqdn
from subprocess import run
from threading import Lock
from time import time
from typing import Any

from dateutil import rrule
# TODO: switch to zoneinfo with https://github.com/py-vobject/vobject/pull/118
from pytz import timezone as ZoneInfo
from tzlocal import get_localzone_name
from vobject import iCalendar
from vobject.base import Component, readOne
from vobject.icalendar import TimezoneComponent


class Remind:
    """Represents a collection of Remind files."""

    def __init__(
        self,
        filename: str | None = None,
        localtz: str | None = None,
        startdate: date | None = None,
        month: int = 15,
        alarm: timedelta | None = None,
        fqdn: str | None = None,
    ) -> None:
        """Constructor.

        filename -- the remind file (included files will be used as well)
        localtz -- the timezone of the remind file
        startdate -- the date to start parsing, will be passed to remind
        month -- how many month to parse, will be passed to remind -s
        """
        self._filename = filename or expanduser("~/.reminders")
        self._localtz = ZoneInfo(localtz or get_localzone_name())
        self._startdate = startdate or date.today() - timedelta(weeks=12)
        self._month = month
        self._alarm = alarm or timedelta(minutes=-10)
        self._lock = Lock()
        self._reminders: dict[str, dict[str, Any]] = {}
        self._mtime = 0.0
        self._fqdn = fqdn or getfqdn()

    def _parse_remind(self, filename: str, lines: str = "") -> dict[str, dict[str, Any]]:
        """Call remind and parse output into a dict.

        filename -- the remind file (included files will be used as well)
        lines -- used as stdin to remind (filename will be set to -)
        """
        cmd = [
            "remind",
            f"-pppq{self._month}",
            "-b2",
            "-y",
            "-df",
            filename,
            str(self._startdate),
        ]
        try:
            process = run(cmd, input=lines, capture_output=True, check=False, text=True)
        except FileNotFoundError as error:
            raise FileNotFoundError("remind command not found, please install it") from error

        if "Unknown option" in process.stderr:
            raise OSError(f'Error running: {" ".join(cmd)}, maybe old remind version')

        if (
            f"Can't open file: {filename}" in process.stderr
            or f"Error reading {filename}: Can't open file" in process.stderr
        ):
            return {filename: {}}

        if "): Parse error" in process.stderr:
            return {filename: {}}

        err = list(set(findall(r"Can't open file: (.*)", process.stderr)))
        if err:
            raise FileNotFoundError(f'include file(s): {", ".join(err)} not found (please use absolute paths)')

        reminders: dict[str, dict[str, Any]] = {}
        for source in list(set(findall(r"Caching file `(.*)' in memory", process.stderr))):
            reminders[source] = {}
            if isfile(source):
                # There is a race condition with the remind call above here.
                mtime = getmtime(source)
                if mtime > self._mtime:
                    self._mtime = mtime

        try:
            months = loads(process.stdout)
        except JSONDecodeError as exc:
            raise OSError(f'Error parsing: {" ".join(cmd)}, maybe old remind version') from exc

        for month in months:
            for entry in month["entries"]:
                # man remind:
                # If you use the sequence %"%" in a MSG or CAL-type reminder,
                # then no calendar entry is produced for that reminder.
                if '%"%"' in entry["body"] and entry["calendar_body"] == "":
                    continue
                # man remind:
                # A back-end must ignore a SPECIAL that it does not recognize.
                # Note that the COLOR special is an exception; it downgrades to
                # the equivalent of MSG in Remind's normal mode of operation.
                if "passthru" in entry and entry["passthru"] != "COLOR":
                    continue

                entry["uid"] = f"{entry['tags'].split(',')[-1][7:]}@{self._fqdn}"

                if "eventstart_in_tz" in entry:
                    dtstart: datetime | date = datetime.strptime(entry["eventstart_in_tz"], "%Y-%m-%dT%H:%M").replace(
                        tzinfo=ZoneInfo(entry["tz"])
                    )
                elif "eventstart" in entry:
                    dtstart: datetime | date = datetime.strptime(entry["eventstart"], "%Y-%m-%dT%H:%M").replace(
                        tzinfo=self._localtz
                    )
                else:
                    dtstart = datetime.strptime(entry["date"], "%Y-%m-%d").date()

                filename = entry["filename"]
                if filename == "-stdin-":  # changed in remind 05.05.00
                    filename = "-"
                if entry["uid"] in reminders[filename]:
                    if dtstart not in reminders[filename][entry["uid"]]["dtstart"]:
                        reminders[filename][entry["uid"]]["dtstart"].append(dtstart)
                else:
                    entry["dtstart"] = [dtstart]
                    reminders[filename][entry["uid"]] = entry

        return reminders

    @staticmethod
    def _interval(dates: list[date]) -> int:
        """Return the distance between all dates and 0 if they are different."""
        interval = (dates[1] - dates[0]).days
        last = dates[0]
        for dat in dates[1:]:
            if (dat - last).days != interval:
                return 0
            last = dat
        return interval

    @staticmethod
    def _gen_dtend_rrule(dtstarts: list[date], vevent: Component) -> None:
        """Generate an rdate or rrule from a list of dates and add it to the vevent."""
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
                vevent.add("dtend").value = dtstarts[-1] + timedelta(days=1)
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
                vevent.add("dtend").value = dtstarts[0] + timedelta(days=1)

    def _gen_vevent(self, event: dict[str, Any], vevent: Component) -> None:
        """Generate vevent from given event."""
        vevent.add("dtstart").value = event["dtstart"][0]

        # man rem2ps
        # If your back-end is designed to draw a calendar,
        # then it should use the calendar_body if present.
        # ..and if not, then it should fall back on the body.
        vevent.add("summary").value = event.get("calendar_body", event["body"])

        if "info" in event:
            if "description" in event["info"]:
                vevent.add("description").value = event["info"]["description"]
            if "location" in event["info"]:
                vevent.add("location").value = event["info"]["location"]
            if "url" in event["info"]:
                vevent.add("url").value = event["info"]["url"]

        vevent.add("dtstamp").value = datetime.fromtimestamp(self._mtime)
        vevent.add("uid").value = event["uid"]

        if "tags" in event:
            tags = event["tags"].split(",")[:-1]

            classes = ["PUBLIC", "PRIVATE", "CONFIDENTIAL"]

            tag_class = [tag for tag in tags if tag in classes]
            if tag_class:
                vevent.add("class").value = tag_class[0]

            statuses = ["TENTATIVE", "CONFIRMED", "CANCELLED"]
            tag_status = [status for status in tags if status in statuses]
            if tag_status:
                vevent.add("status").value = tag_status[0]

            categories = [tag for tag in tags if tag not in classes and tag not in statuses]

            if categories:
                vevent.add("categories").value = categories

        if isinstance(event["dtstart"][0], datetime):
            if self._alarm != timedelta():
                valarm = vevent.add("valarm")
                valarm.add("trigger").value = self._alarm
                valarm.add("action").value = "DISPLAY"
                valarm.add("description").value = vevent.summary.value

            if "eventduration" in event:
                vevent.add("duration").value = timedelta(minutes=event["eventduration"])
            else:
                vevent.add("dtend").value = event["dtstart"][0]

        elif len(event["dtstart"]) == 1:
            vevent.add("dtend").value = event["dtstart"][0] + timedelta(days=1)

        if len(event["dtstart"]) > 1:
            Remind._gen_dtend_rrule(event["dtstart"], vevent)

    def _update(self) -> None:
        """Reload Remind files if the mtime is newer."""
        update = not self._reminders

        now = time()
        if self._mtime > 0 and datetime.fromtimestamp(self._mtime).date() < datetime.fromtimestamp(now).date():
            update = True
            self._mtime = now

        with self._lock:
            for fname in self._reminders:
                if not isfile(fname) or getmtime(fname) > self._mtime:
                    update = True
                    break

            if update:
                self._reminders = self._parse_remind(self._filename)

    def get_filesnames(self) -> list[str]:
        """All filenames parsed by remind (including included files)."""
        self._update()
        return sorted(self._reminders.keys())

    def _get_uid(self, line: str) -> str:
        """UID of a remind line."""
        return f"{md5(line.strip().encode('utf-8')).hexdigest()}@{self._fqdn}"

    def get_uids(self, filename: str = "") -> list[str]:
        """UIDs of all reminders in the file excluding included files.

        If a filename is specified, only it's UIDs are return, otherwise all.

        filename -- the remind file
        """
        self._update()

        if filename:
            if filename not in self._reminders:
                return []
            return list(self._reminders[filename].keys())
        return [uid for uids in self._reminders.values() for uid in uids]

    def _vobject_etag(self, filename: str, uid: str) -> tuple[str, Component, str]:
        """Return iCal object and etag of one Remind entry.

        filename -- the remind file
        uid -- the UID of the Remind line
        """
        cal = iCalendar()
        self._gen_vevent(self._reminders[filename][uid], cal.add("vevent"))
        return uid, cal, self.get_etag(cal)

    def to_vobject_etag(self, filename: str, uid: str) -> tuple[Component, str]:
        """Return iCal object and etag of one Remind entry.

        filename -- the remind file
        uid -- the UID of the Remind line
        """
        self._update()

        return self._vobject_etag(filename, uid)[1:3]

    def to_vobjects(self, filename: str, uids: Iterable[str] | None = None) -> list[tuple[str, Component, str]]:
        """Return iCal objects and etags of all Remind entries in uids.

        filename -- the remind file
        uids -- the UIDs of the Remind lines (all if None)
        """
        self._update()

        if not uids:
            uids = list(self._reminders[filename].keys())

        return [self._vobject_etag(filename, uid) for uid in uids]

    def to_vobject(self, filename: str = "", uid: str = "") -> Component:
        """Return iCal object of Remind lines.

        If filename and UID are specified, the vObject only contains that event.
        If only a filename is specified, the vObject contains all events in the file.
        Otherwise the vObject contains all all objects of all files associated
        with the Remind object.

        filename -- the remind file
        uid -- the UID of the Remind line
        """
        self._update()

        cal = iCalendar()
        if uid:
            self._gen_vevent(self._reminders[filename][uid], cal.add("vevent"))
        elif filename:
            for event in self._reminders[filename].values():
                self._gen_vevent(event, cal.add("vevent"))
        else:
            for events in self._reminders.values():
                for event in events.values():
                    self._gen_vevent(event, cal.add("vevent"))
        return cal

    def stdin_to_vobject(self, lines: str) -> Component:
        """Return iCal object of the Remind commands in lines."""
        cal = iCalendar()
        for event in self._parse_remind("-", lines)["-"].values():
            self._gen_vevent(event, cal.add("vevent"))
        return cal

    @staticmethod
    def _parse_rdate(rdates: list[date], repeat: int = 1) -> list[str]:
        """Convert from iCal rdate to Remind trigdate syntax."""
        rdates = sorted(rdates)
        if len(rdates) == 1 and repeat == 1:
            return [rdates[0].strftime("%Y-%m-%d")]
        start = rdates[0].strftime("FROM %Y-%m-%d")
        trigdates = [(rdate + timedelta(days=d)).strftime("$T=='%Y-%m-%d'") for rdate in rdates for d in range(repeat)]
        end = (rdates[-1] + timedelta(days=repeat - 1)).strftime("UNTIL %Y-%m-%d")
        return [start, end, f"SATISFY [{'||'.join(trigdates)}]"]

    @staticmethod
    def _parse_rruleset(rruleset: Any, duration: timedelta) -> str | list[str]:
        """Convert from iCal rrule to Remind recurrence syntax."""
        # pylint: disable=protected-access

        if duration.days > 1:
            return " ".join(Remind._parse_rdate(rruleset._rrule[0], duration.days))

        if rruleset._rrule[0]._freq == 0:
            return []

        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        rep = []
        if rruleset._rrule[0]._byweekday and len(rruleset._rrule[0]._byweekday) > 1:
            rep.append("*1")
        elif rruleset._rrule[0]._freq == rrule.DAILY:
            rep.append(f"*{rruleset._rrule[0]._interval}")
        elif rruleset._rrule[0]._freq == rrule.WEEKLY:
            rep.append(f"*{(7 * rruleset._rrule[0]._interval)}")
        elif rruleset._rrule[0]._freq == rrule.MONTHLY and rruleset._rrule[0]._bymonthday:
            rep.append(str(rruleset._rrule[0]._bymonthday[0]))
        elif rruleset._rrule[0]._freq == rrule.MONTHLY and rruleset._rrule[0]._bynweekday:
            daynum, week = rruleset._rrule[0]._bynweekday[0]
            weekday = weekdays[daynum]
            rep.append(f"{weekday} {week * 7 - 6}")
        else:
            return " ".join(Remind._parse_rdate(rruleset._rrule[0]))

        if rruleset._rrule[0]._byweekday and len(rruleset._rrule[0]._byweekday) > 1:
            daynums = set(range(7)) - set(rruleset._rrule[0]._byweekday)
            days = [weekdays[day] for day in daynums]
            rep.append(f"SKIP OMIT {' '.join(days)}")

        if rruleset._rrule[0]._until:
            rep.append(rruleset._rrule[0]._until.strftime("UNTIL %b %d %Y").replace(" 0", " "))
        elif rruleset._rrule[0]._count:
            rep.append(rruleset[-1].strftime("UNTIL %b %d %Y").replace(" 0", " "))

        return rep

    @staticmethod
    def _event_duration(vevent: Component) -> timedelta:
        """Unify dtend and duration to the duration of the given vevent."""
        if hasattr(vevent, "dtend"):
            return vevent.dtend.value - vevent.dtstart.value
        if hasattr(vevent, "duration") and vevent.duration.value:
            return vevent.duration.value
        return timedelta(0)

    @staticmethod
    def _gen_msg(vevent: Component, label: str, tail: str) -> str:
        """Generate a Remind MSG from the given vevent."""
        msg = ["MSG"]

        if label:
            msg.append(label)

        if hasattr(vevent, "summary") and vevent.summary.value:
            msg.append(Remind._rem_clean(vevent.summary.value))
        else:
            msg.append("empty reminder")

        if tail:
            msg.append(tail)

        return " ".join(msg)

    @staticmethod
    def _rem_clean(rem: str) -> str:
        """Cleanup string for Remind.

        Strip, transform newlines, and escape '[' in string so it's acceptable
        as a remind entry.
        """
        return rem.strip().replace("%", "%%").replace("\n", "%_").replace("[", "[[")

    @staticmethod
    def _rem_info_clean(rem: str) -> str:
        """Cleanup INFO string for Remind.
        """
        return rem.strip().replace("\n", r"\n").replace("[", "[[").replace('"', r'\"')

    @staticmethod
    def _abbr_tag(tag: str) -> str:
        """Transform a string so it's acceptable as a remind tag."""
        return tag.replace(" ", "")[:48]

    def to_remind(
        self,
        vevent: Component,
        label: str = "",
        priority: str = "",
        tags: str = "",
        tail: str = "",
        postdate: str = "",
        posttime: str = "",
    ) -> str:
        """Generate a Remind command from the given vevent."""
        remind = ["REM"]

        duration = Remind._event_duration(vevent)

        trigdates = None
        if hasattr(vevent, "rrule"):
            trigdates = Remind._parse_rruleset(vevent.rruleset, duration)

        dtstart = vevent.dtstart.value
        # If we don't get timezone information, handle it as a naive datetime.
        # See https://github.com/jspricke/python-remind/issues/2 for reference.
        if isinstance(dtstart, datetime) and dtstart.tzinfo is None:
            dtstart = dtstart.astimezone(self._localtz)

        dtend = None
        if hasattr(vevent, "dtend"):
            dtend = vevent.dtend.value
        if isinstance(dtend, datetime) and dtend.tzinfo:
            dtend = dtend.astimezone(self._localtz)

        if not hasattr(vevent, "rdate") and not isinstance(trigdates, str):
            if not hasattr(vevent, "rrule") or vevent.rruleset._rrule[0]._freq != rrule.MONTHLY:
                remind.append(dtstart.strftime("%b %d %Y").replace(" 0", " "))
            elif hasattr(vevent, "rrule") and vevent.rruleset._rrule[0]._freq == rrule.MONTHLY and trigdates:
                remind.extend(trigdates)
                trigdates = dtstart.strftime("SATISFY [$T>='%Y-%m-%d']")

        if postdate:
            remind.append(postdate)

        if priority:
            remind.append(f"PRIORITY {priority}")

        if isinstance(trigdates, list):
            remind.extend(trigdates)

        if type(dtstart) is date and duration.days > 1 and not hasattr(vevent, "rrule"):
            remind.append("*1")
            if dtend is not None:
                dtend -= timedelta(days=1)
                remind.append(dtend.strftime("UNTIL %b %d %Y").replace(" 0", " "))

        if isinstance(dtstart, datetime):
            remind.append(dtstart.strftime("AT %H:%M").replace(" 0", " "))

            if posttime:
                remind.append(posttime)

        if hasattr(vevent, "rdate"):
            rdates = {rdate for rdate in vevent.rdate.value}
            rdates.add(dtstart)
            parsed_rdates = Remind._parse_rdate(list(rdates))
            if len(parsed_rdates) > 1:
                trigdates = parsed_rdates[2]
                remind.extend(parsed_rdates[:2])
            else:
                remind.append(parsed_rdates[0])

        if isinstance(dtstart, datetime) and duration.total_seconds() > 0:
            hours, minutes = divmod(duration.total_seconds() / 60, 60)
            remind.append(f"DURATION {hours:.0f}:{minutes:02.0f}")

        if hasattr(vevent, "class"):
            remind.append(f"TAG {Remind._abbr_tag(vevent.getChildValue('class'))}")

        if hasattr(vevent, "status"):
            remind.append(f"TAG {Remind._abbr_tag(vevent.getChildValue('status'))}")

        if tags:
            remind.extend([f"TAG {Remind._abbr_tag(tag)}" for tag in tags])

        if hasattr(vevent, "categories_list"):
            for categories in vevent.categories_list:
                for category in categories.value:
                    remind.append(f"TAG {Remind._abbr_tag(category)}")

        if isinstance(dtstart, datetime):
            tzid = TimezoneComponent.pickTzid(dtstart.tzinfo)
            if tzid is None:
                tzid = "UTC"
            if TimezoneComponent.pickTzid(self._localtz) != tzid:
                remind.append(f"TZ {tzid}")

        if hasattr(vevent, "description") and vevent.description.value:
            remind.append(f'INFO "Description: {Remind._rem_info_clean(vevent.description.value)}"')

        if hasattr(vevent, "location") and vevent.location.value:
            remind.append(f'INFO "Location: {Remind._rem_info_clean(vevent.location.value)}"')

        if hasattr(vevent, "url") and vevent.url.value:
            remind.append(f'INFO "Url: {Remind._rem_info_clean(vevent.url.value)}"')

        if isinstance(trigdates, str):
            remind.append(trigdates)

        remind.append(Remind._gen_msg(vevent, label, tail))

        return " ".join(remind) + "\n"

    def to_reminders(
        self,
        ical: Component,
        label: str = "",
        priority: str = "",
        tags: str = "",
        tail: str = "",
        postdate: str = "",
        posttime: str = "",
    ) -> str:
        """Return Remind commands for all events of a iCalendar."""
        if not hasattr(ical, "vevent_list"):
            return ""

        reminders = [
            self.to_remind(vevent, label, priority, tags, tail, postdate, posttime)
            for vevent in ical.vevent_list
        ]
        return "".join(reminders)

    def append_vobject(self, ical: Component, filename: str = "") -> str:
        """Append a Remind command generated from the iCalendar to the file."""
        if not filename:
            filename = self._filename

        with self._lock:
            outdat = self.to_reminders(ical)
            with open(filename, "a", encoding="utf-8") as outfile:
                outfile.write(outdat)

        return self._get_uid(outdat)

    def remove(self, uid: str, filename: str = "") -> None:
        """Remove the Remind command with the uid from the file."""
        if not filename:
            filename = self._filename

        uid = uid.split("@")[0]

        with self._lock:
            with open(filename, encoding="utf-8") as infile:
                rem = infile.readlines()
            for index, line in enumerate(rem):
                if uid == md5(line.strip().encode("utf-8")).hexdigest():
                    del rem[index]
                    with open(filename, "w", encoding="utf-8") as outfile:
                        outfile.writelines(rem)
                    break

    def replace_vobject(self, uid: str, ical: Component, filename: str = "") -> str:
        """Update the Remind command with the uid in the file with the new iCalendar."""
        if not filename:
            filename = self._filename

        uid = uid.split("@")[0]

        with self._lock:
            with open(filename, encoding="utf-8") as infile:
                rem = infile.readlines()
            for index, line in enumerate(rem):
                if uid == md5(line.strip().encode("utf-8")).hexdigest():
                    rem[index] = self.to_reminders(ical)
                    new_uid = self._get_uid(rem[index])
                    with open(filename, "w", encoding="utf-8") as outfile:
                        outfile.writelines(rem)
                    return new_uid
        raise ValueError(f"Failed to find uid {uid} in {filename}")

    def move_vobject(self, uid: str, from_file: str, to_file: str) -> None:
        """Move the Remind command with the uid from from_file to to_file."""
        uid = uid.split("@")[0]

        with self._lock:
            with open(from_file, encoding="utf-8") as infile:
                rem = infile.readlines()
            for index, line in enumerate(rem):
                if uid == md5(line.strip().encode("utf-8")).hexdigest():
                    del rem[index]
                    with open(from_file, "w", encoding="utf-8") as outfile:
                        outfile.writelines(rem)
                    with open(to_file, "a", encoding="utf-8") as outfile:
                        outfile.writelines(rem)
                    break

    @staticmethod
    def get_meta() -> dict[str, str]:
        """Meta tags of the vObject collection."""
        return {"tag": "VCALENDAR", "C:supported-calendar-component-set": "VEVENT"}

    def last_modified(self) -> float:
        """Last time the Remind files where parsed."""
        self._update()
        return self._mtime

    @staticmethod
    def get_etag(vobject: Component) -> str:
        """Generate an etag for the given vobject.

        This sets the dtstamp to epoch 0 to generate a deterministic result as
        Remind doesn't save a dtstamp for every entry. And etag should only
        change if the other values actually change.

        """
        vobject_copy = iCalendar()
        vobject_copy.copy(vobject)

        for vevent in vobject_copy.vevent_list:
            vevent.dtstamp.value = datetime.fromtimestamp(0)
        etag = md5()
        etag.update(vobject_copy.serialize().encode("utf-8"))
        return f'"{etag.hexdigest()}"'


def rem2ics() -> None:
    """Command line tool to convert from Remind to iCalendar."""
    # pylint: disable=maybe-no-member
    from argparse import ArgumentParser, FileType
    from sys import stdin, stdout

    from dateutil.parser import parse

    parser = ArgumentParser(description="Converter from Remind to iCalendar syntax.")
    parser.add_argument(
        "-s",
        "--startdate",
        type=lambda s: parse(s).date(),
        default=date.today() - timedelta(weeks=12),
        help="Start offset for remind call (default: -12 weeks)",
    )
    parser.add_argument(
        "-m",
        "--month",
        type=int,
        default=15,
        help="Number of month to generate calendar beginning wit startdate (default: 15)",
    )
    parser.add_argument(
        "-a",
        "--alarm",
        type=int,
        default=-10,
        help="Trigger time for the alarm before the event in minutes (default: -10)",
    )
    parser.add_argument("-z", "--zone", help="Timezone of Remind file (default: local timezone)")
    parser.add_argument(
        "infile",
        nargs="?",
        default=expanduser("~/.reminders"),
        help="The Remind file to process (default: ~/.reminders)",
    )
    parser.add_argument(
        "outfile",
        nargs="?",
        type=FileType("w", encoding="utf-8"),
        default=stdout,
        help="Output iCalendar file (default: stdout)",
    )
    args = parser.parse_args()

    if args.infile and args.infile != "-" and not isfile(args.infile) and not args.outfile:
        args.outfile = open(args.infile, "w", encoding="utf-8")
        args.infile = None

    if args.infile == "-":
        remind = Remind(args.infile, args.zone, args.startdate, args.month, timedelta(minutes=args.alarm))
        vobject = remind.stdin_to_vobject(stdin.read())
        if vobject:
            args.outfile.write(vobject.serialize())
    else:
        remind = Remind(args.infile, args.zone, args.startdate, args.month, timedelta(minutes=args.alarm))
        args.outfile.write(remind.to_vobject().serialize())


def ics2rem() -> None:
    """Command line tool to convert from iCalendar to Remind."""
    from argparse import ArgumentParser, FileType
    from sys import stdin, stdout

    parser = ArgumentParser(description="Converter from iCalendar to Remind syntax.")
    parser.add_argument("-l", "--label", help="Text to prepand to every remind summary")
    parser.add_argument("-p", "--priority", type=int, help="Priority for every Remind entry (0..9999)")
    parser.add_argument("-t", "--tag", action="append", help="Tag(s) for every Remind entry")
    parser.add_argument("--tail", help="Text to append to every remind summary")
    parser.add_argument(
        "--postdate",
        help="String to follow the date in every Remind entry. "
        'Useful for entering "back" and "delta" fields (see man remind).',
    )
    parser.add_argument(
        "--posttime",
        help="String to follow the time in every timed Remind entry. "
        'Useful for entering "tdelta" and "trepeat" fields (see man remind).',
    )
    parser.add_argument("-z", "--zone", help="Timezone of Remind file (default: local timezone)")
    parser.add_argument(
        "infile",
        nargs="?",
        type=FileType("r", encoding="utf-8"),
        default=stdin,
        help="Input iCalendar file (default: stdin)",
    )
    parser.add_argument(
        "outfile",
        nargs="?",
        type=FileType("w", encoding="utf-8"),
        default=stdout,
        help="Output Remind file (default: stdout)",
    )
    args = parser.parse_args()

    vobject = readOne(args.infile.read())
    rem = Remind(localtz=args.zone).to_reminders(
        vobject,
        args.label,
        args.priority,
        args.tag,
        args.tail,
        args.postdate,
        args.posttime,
    )
    args.outfile.write(rem)
