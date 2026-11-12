"""Hourly snapshot of the site's anonymous usage counters (abacus) into stats.json.

Runs in GitHub Actions. Reads the course list from index.html in the main checkout,
reuses finished days from the previous stats.json, and refuses to overwrite good data
when the counter service is failing.
"""
import datetime
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

BASE = 'https://abacus.jasoncameron.dev/get/yanshufim-orot/'
START = datetime.date(2026, 11, 3)
SITE = pathlib.Path(sys.argv[1])   # main checkout (index.html)
OUT = pathlib.Path(sys.argv[2])    # stats.json on the stats branch

failures = 0
requests = 0


def get(key):
    """Counter value; 0 for a key never hit; None if the service could not answer."""
    global failures, requests
    requests += 1
    time.sleep(0.15)  # the service blocks bursts
    for attempt in range(5):
        try:
            with urllib.request.urlopen(BASE + key, timeout=15) as r:
                return json.load(r).get('value', 0)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 0
            time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    failures += 1
    return None


html = (SITE / 'index.html').read_text(encoding='utf-8')
data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
courses = [(c['id'], c.get('short') or c['name']) for c in data['courses']]

prev = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
prev_days = {d['date']: d for d in prev.get('days', [])}

now = datetime.datetime.now(ZoneInfo('Asia/Jerusalem'))
today = now.date()

days = []
d = START
while d <= today:
    iso = d.isoformat()
    # A day older than two days is final: keep it instead of asking again
    if iso in prev_days and (today - d).days > 2:
        days.append(prev_days[iso])
    else:
        days.append({'date': iso, 'visits': get('day-' + iso), 'devices': get('uniq-' + iso), 'returning': get('ret-' + iso)})
    d += datetime.timedelta(days=1)

totals = {k: get(k) for k in ('people', 'visits', 'returning', 'from-homescreen', 'scrolled', 'act-task-done')}
acts = {k: get('act-' + k) for k in ('summary', 'folder', 'recording', 'zoom', 'lemida', 'calendar', 'gmail', 'copy-mail', 'install', 'other')}
stay = {k: get('stay2-' + k) for k in ('0-10s', '10-30s', '30-60s', '1-2m', '2-5m', '5-10m', '10m-plus')}
clicks = {k: get('clicks-' + k) for k in ('0', '1', '2-3', '4-6', '7-plus')}
os_ = {k: get('os-' + k) for k in ('ios', 'android', 'desktop')}
course_rows = [{'id': cid, 'name': name, 'opens': get('course-' + cid), 'summaries': get('act-summary-' + cid),
                'recordings': get('act-recording-' + cid), 'zoom': get('act-zoom-' + cid)} for cid, name in courses]

if failures > max(3, requests // 5):
    print(f'counter service failing: {failures} of {requests} requests; keeping the last snapshot', file=sys.stderr)
    sys.exit(1)

# One history entry per day of the cumulative counters, so weeks can be compared later
history = [h for h in prev.get('history', []) if h['date'] != today.isoformat()]
history.append({'date': today.isoformat(), 'totals': totals, 'acts': acts,
                'opens': {r['id']: r['opens'] for r in course_rows}})

stats = {'updated': now.isoformat(timespec='minutes'), 'failures': failures, 'totals': totals, 'days': days,
         'acts': acts, 'stay': stay, 'clicks': clicks, 'os': os_, 'courses': course_rows, 'history': history}
OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'ok: {requests} requests, {failures} failed')
