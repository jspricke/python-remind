Python Remind library
=====================

Python library to convert between `Remind <https://dianne.skoll.ca/projects/remind/>`_ and iCalendar.
Can be used stand alone (provided rem2ics and ics2rem tools) as well as integrated as a CalDAV client or server.

Installation
------------

You need to have the Remind command line tool installed.
For Debian/Ubuntu use::

  $ sudo apt-get install remind

Using pip
~~~~~~~~~

::

  $ pip install remind

This will install all Python dependencies as well.

Using python-setuptools
~~~~~~~~~~~~~~~~~~~~~~~

::

  $ python setup.py install

Set up a Remind CalDAV server
-----------------------------

Have a look at `radicale-remind <https://github.com/jspricke/radicale-remind>`_

Sync to an external iCalendar server (http; cron)
-------------------------------------------------

::

  curl URL | ics2rem >> ~/.reminders

Sync to an external CalDAV server
---------------------------------

Have a look at `remind-caldav <https://github.com/jspricke/remind-caldav>`_

Share your calendar using http
------------------------------

::

  rem2ics > /var/www/html/my.ics

Publish the URL and use these guides to integrate it into other calendar software:

* `Thunderbird/Lightning <https://mzl.la/1BsOArH>`_ (Section: On the Network)
* `Google Calendar <https://support.google.com/calendar/answer/37100>`_
* `Apple Calendar <https://support.apple.com/kb/PH11523>`_

Format of the Remind MSG body
-----------------------------

::

  %" summary at location %" description

The ``%"`` is omitted, if there is no description in the iCalendar.

Known limitations
-----------------

iCalendar -> Remind
~~~~~~~~~~~~~~~~~~~

* RECURRENCE-ID is not supported at the moment. This is a limitation of the used python-vobject library, see http://lists.skyhouseconsulting.com/pipermail/vobject/2009-September/000204.html.

Remind -> iCalendar
~~~~~~~~~~~~~~~~~~~

* Events are only evaluated in the given time frame, so events extending it, are cut of (birthday reminders for example).
* Complex reminders are only preserved in their evaluated form (PUSH-OMIT-CONTEXT, OMIT, TRIGGER, BEFORE, SKIP).
  Same holds true for function evaluation in MSG. For example having the age in a birthday reminder results in the same string for every year.
* Periodic reminders other then daily or weekly are not preserved.
* Two entries with the same content are only exported once.
