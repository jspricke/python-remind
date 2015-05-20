# Python Remind library

Python library to convert between [Remind](http://www.roaringpenguin.com/products/remind) and iCalendar.
Can be used stand alone (provided rem2ics and ics2rem tools) as well as integrated as a CalDAV client or server.

# Installation

Uses python-setuptools:
```
python setup.py install
```

You need to have the remind command line tool installed as well.

## Set up a Remind CalDAV server

Have a look at [radicale-remind](http://github.com/jspricke/radicale-remind)

## Sync to an external iCalendar server (http; cron)

Use curl URL | ics2rem

## Sync to an external CalDAV server

Have a look at [remind-caldav](http://github.com/jspricke/remind-caldav)

## Share your calendar using http

rem2ics > /var/www/html/my.ics

Publish the URL and use these guides to integrate it into other calendar software:
- [Thunderbird/Lightning](http://mzl.la/1BsOArH) (Section: On the Network)
- [Google Calendar](https://support.google.com/calendar/answer/37100)
- [Apple Calendar](https://support.apple.com/kb/PH11523)

## Format of the Remind MSG body

`%" summary at location %" description`

The `%"` is omitted, if there is no description in the iCalendar.

## ``ics_compare.py``

There is a similar program in python-vobject ``ics_diff.py``.

## Known limitations

### iCalendar -> Remind

- RECURRENCE-ID is not supported at the moment. This is a limitation of the used python-vobject library, see http://lists.skyhouseconsulting.com/pipermail/vobject/2009-September/000204.html.

### Remind -> iCalendar

- Events are only evaluated in the given time frame, so events extending it, are cut of (birthday reminders for example).
- Complex reminders are only preserved in their evaluated for (PUSH-OMIT-CONTEXT, OMIT, TRIGGER, BEFORE, SKIP).
- Periodic reminders other then daily or weekly are not preserved
