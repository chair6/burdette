#!/usr/bin/env python

import os, sys, datetime, time, json, sqlite3, socket
import urllib2, urlparse
import difflib
from BeautifulSoup import BeautifulSoup
import smtplib
from email.mime.text import MIMEText

event_types = { "INFO":"INFO", "WARN":"WARN", "FAIL":"FAIL" }

if len(sys.argv) != 2:
    print("Usage: %s [configfile]\n" % sys.argv[0])
    sys.exit(1)

configfile = sys.argv[1]
configname = None
if configfile.endswith(".json") or configfile.endswith(".cfg"):
    configname = "".join(os.path.split(configfile)[1].split(".")[:-1])
else: 
    configname = os.path.split(configfile)[1]

path = os.path.dirname(os.path.realpath(__file__))
db_file = os.path.join(path, "%s.db" % configname)

config = None
conn = None

try:
    with open(configfile, "r") as fin:
        config = json.loads(fin.read())
except IOError as e:
    print("Config file '%s' cannot be opened/read." % configfile)
    sys.exit(1)
except ValueError as e:
    print("Config file '%s' cannot be parsed as JSON [%s]." % (configfile, e))
    sys.exit(1)

ts = datetime.datetime.utcnow()
log_file = open(os.path.join(path, "%s.log" % configname), "a")
default_timeout = config.get('default_timeout', 20)

def open_db(dbfile):
    exists = True if os.path.exists(dbfile) else False
    global conn
    conn = sqlite3.connect(dbfile)
    conn.row_factory = sqlite3.Row
    if not exists:
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE baselines (id integer primary key autoincrement, timestamp text, url text, data blob)""")
        cursor.execute("""CREATE TABLE diffs (id integer primary key autoincrement, timestamp text, url text, ratio text, diff blob)""")
        cursor.execute("""CREATE TABLE events (id integer primary key autoincrement, timestamp text, event text)""")
        cursor.execute("""CREATE TABLE alerts (id integer primary key autoincrement, timestamp text, type text, url text)""")
        log_event(event_types["INFO"], "Initialized tracking databases")
        conn.commit()
    return conn

def save_diff(timestamp, url, ratio, diff):
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO diffs VALUES (NULL, ?, ?, ?, ?)""", (timestamp, url, ratio, diff))
    conn.commit()

def log_event(event_type, text):
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO events VALUES (NULL, ?, ?)""", (ts, "%s - %s" % (event_types[event_type], text)))
    conn.commit()
    time_now = datetime.datetime.now().isoformat()
    log_file.write("%s - %s - %s\n" % (time_now, event_type, text))
    print("%s\t%s" % (event_type, text))

def set_baseline(timestamp, url, data):
    cursor = conn.cursor()
    data = "\n".join(data)
    if get_baseline(url) == None:
        cursor.execute("""INSERT INTO baselines VALUES (NULL, ?, ?, ?)""", (timestamp, url, data))
    else:
        cursor.execute("""UPDATE baselines SET timestamp = ?, url = ?, data = ? WHERE url = ?""", (timestamp, url, data, url))
    conn.commit()

def get_baseline(url):
    cursor = conn.cursor()
    cursor.execute("""SELECT data FROM baselines WHERE url = ?""", ([url]))
    results = cursor.fetchone()
    if results != None:
        results = results[0].split("\n")
    return results

def recent_alerts(url, ts, alert_type):
    boundary_ts = ts - datetime.timedelta(minutes=config.get('alert_repeat_minutes', 30))
    cursor = conn.cursor()
    cursor.execute("""SELECT * FROM alerts WHERE url = ? AND type = ? AND timestamp > ?""", (url, alert_type, boundary_ts))
    result = True if cursor.fetchone() != None else False
    cursor.execute("""DELETE FROM alerts WHERE timestamp < ?""", ([boundary_ts]))
    return result

def log_alert(url, ts, alert_type):
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO alerts VALUES (NULL, ?, ?, ?)""", (ts, alert_type, url))
    conn.commit()

def get_url(url):
    content, errmsg = None, None
    try:
        response = urllib2.urlopen(url, None, default_timeout)
        split_content_type = response.headers.get("content-type", "text/html; charset=utf-8").split("charset=")
        encoding = "utf-8"
        if len(split_content_type) > 1:
            encoding = split_content_type[-1]
        content = [unicode(line.rstrip(), encoding) for line in response.readlines()]
    except urllib2.URLError as e:
        errmsg = e.reason
    except socket.timeout as e:
        errmsg = e
    return (content, errmsg)

def test_externals(html):
    externals = set()
    soup = BeautifulSoup("\n".join(html))
    for tag_name in ["a", "area", "base", "link"]:
        for tag in soup.findAll(tag_name):
            externals.add(tag.get("href", ""))
    for tag_name in ["img", "script", "iframe", "frame", "input"]:
        for tag in soup.findAll(tag_name):
            externals.add(tag.get("src", ""))
    bad_externals = set()
    for ext in externals:
        hostname = urlparse.urlparse(ext).hostname
        if hostname != None:
            trusted = False
            for src in config["trusted_srcs"]:
                if hostname.endswith(src):
                    trusted = True
            if not trusted:
                bad_externals.add(hostname)
    return bad_externals

def send_alert(msgtext):
    msg = MIMEText(msgtext.encode("utf-8"), "plain", "utf-8")
    msg["Subject"] = "WebCheck alert"
    msg["From"] = config["alert_from"]
    msg["To"] = ", ".join(config["alert_to"])
    
    try:
        s = smtplib.SMTP(config.get("alert_smtprelay", "localhost"))
        s.sendmail(config["alert_from"], config["alert_to"], msg.as_string())
        s.quit()
    except socket.error as e:
        return (False, e)
    else:
        return (True, None)


if config != None:

    alertmsg = []
    alerts = {}

    if conn == None:
        conn = open_db(db_file)

    log_event(event_types["INFO"], "Starting new test run with %s URLs" % (len(config["urls"])))

    for url in config["urls"]:
        log_event(event_types["INFO"], "Testing URL : %s" % url)
        alerts[url] = {"connect":[], "diff":[], "externals":[]}
        baseline = get_baseline(url)
        if baseline == None:
            (html, errmsg) = get_url(url)
            if errmsg:
                log_event(event_types["FAIL"], "Error retrieving %s : %s" % (url, errmsg))
                alerts[url]['connect'].append("Error retrieving %s : %s" % (url, errmsg))
            if html != None:
                set_baseline(ts, url, html)
                log_event(event_types["INFO"], "Wrote new baseline for url : %s" % (url))
        else:
            (html, errmsg) = get_url(url)
            if errmsg:
                log_event(event_types["FAIL"], "Error retrieving %s : %s" % (url, errmsg))
                alerts[url]['connect'].append("Error retrieving %s : %s" % (url, errmsg))
            else:
                m = difflib.SequenceMatcher(None, baseline, html)
                diff_ratio = m.ratio()

                bad_externals = test_externals(html)

                if diff_ratio < config["min_diff_ratio"]:
                    diff_text = "\n".join([line.rstrip() for line in difflib.context_diff(baseline, html, n=1, lineterm="")])
                    log_event(event_types["FAIL"], "Difference detected (%s) in URL %s that is over threshold (%s)" % (diff_ratio, url, config["min_diff_ratio"]))
                    alerts[url]['diff'].append("Difference detected (%s) in URL %s that is over threshold (%s):\n%s\n" % (diff_ratio, url, config["min_diff_ratio"], diff_text))
                    save_diff(ts, url, diff_ratio, diff_text)

                if bad_externals:
                    alerts[url]['externals'].append("Externals in URL %s not in whitelist: \n\t%s" % (url, "\n\t".join(bad_externals)))
                    log_event(event_types["FAIL"], "Externals in URL %s not in whitelist: %s" % (url, ", ".join(bad_externals)))

        for alert_type in alerts[url]:
            if len(alerts[url][alert_type]) > 0:
                if recent_alerts(url, ts, alert_type):
                    log_event(event_types["INFO"], "Recent alerts for %s::%s, not alerting this time" % (alert_type, url))
                else:
                    log_event(event_types["INFO"], "No recent alerts for %s::%s, generating one." % (alert_type, url))
                    alertmsg.extend(alerts[url][alert_type])
                    log_alert(url, ts, alert_type)

    if alertmsg:
        log_event(event_types["WARN"], "Run resulted in issues being identified")
        result, error = None, None
        if "alert_to" in config and len(config["alert_to"]) > 0:
            (success, error) = send_alert("\n\n\n".join(alertmsg))
            if success:
                log_event(event_types["INFO"], "Successfuly sent alert (%s)" % ", ".join(config["alert_to"]))
            else:
                log_event(event_types["FAIL"], "Error sending alert : %s" % error)
        else:
            log_event(event_types["FAIL"], "Did not send alert, 'alert_to' not defined in config")
    else:
        log_event(event_types["INFO"], "Run completed without generating alerts")

