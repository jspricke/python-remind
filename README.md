# Python library to convert between Remind and iCalendar

[Remind](http://www.roaringpenguin.com/products/remind)
Needs python-vobject library.

## How too set up a Remind CalDAV server

Have a look at [radicale-storage](http://github.com/jspricke/radicale-storage)

## How to sync to an external iCalendar server (http; cron)

Use cur URL | ics2rem

## How to sync to an external CalDAV server

Have a look at [remind-caldav](http://github.com/jspricke/remind-caldav)

## ``ics_compare.py``

There is a similar program in python-vobject ``ics_diff.py``.

## Known limitations

### iCalendar -> Remind

- RECURRENCE-ID is not supported at the moment. This is a limitation of the used python-vobject library, see http://lists.skyhouseconsulting.com/pipermail/vobject/2009-September/000204.html.
- RRULEs other then daily and weekly are not implemented.

### Remind -> iCalendar

- Events are only evaluated in the given time frame, so events extending it, are cut of (birthday reminders for example).
- Complex reminders are only preserved in their evaluated for (PUSH-OMIT-CONTEXT, OMIT, TRIGGER, BEFORE, SKIP).
- Periodic reminders other then daily or weekly are not preserved
