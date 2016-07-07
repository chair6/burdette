Burdette
========

Basic web site status / defacement checker. For a configured set of URLs, checks for:
 - Basic HTTP or HTTPS connectivity.
 - Percentage difference between a baseline (collected at time of first run, or when manually triggered) and newly-gathered HTML content.
 - External includes within a page (e.g. \<script src\>, \<a href\>, \<iframe src\>) that are outside of a trusted-externals whitelist.

Reads config from a JSON file, stores details in SQLite database, and alerts via email if configured.

Events are logged into the SQLite database and may need to be cleaned out occasionally.

Setup
-----
Define a JSON config file (see example.json) and configure system cron to execute burdette.py with that config on a regular basis.

    $ cat example.json
    {
        "urls": [
            "http://www.google.com",
            "http://www.facebook.com"
        ],
        "trusted_srcs": [
            "facebook.com", "google.com"
        ],
        "min_diff_ratio": 0.92,
        "alert_from" : "name@server.domain",
        "alert_to": [ "recipient@domain.com", "recipient2@domain2.com" ],
        "alert_smtprelay": "localhost",
        "alert_repeat_minutes": 60,
        "default_timeout": 20
    }

Example cron setup, that executes burdette.py every minute but only sends email output from a cron job once a day (email alerts will still be sent immediately where issues are detected):

    $ cat /etc/crontab | grep burdette
    *  *    * * *   burdette  /home/burdette/burdette.py /home/burdette/example.json >/dev/null 2>&1
    55  6    * * *   burdette  sleep 20; /home/burdette/burdette.py /home/burdette/example.json


Manual Usage
------------

    $ ./burdette.py
    Usage: ./burdette.py [configfile]


