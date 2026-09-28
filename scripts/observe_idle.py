"""Record 30 minutes of idle readiness; reset on jobs or connection changes."""
import json
import os
from pathlib import Path
import time
import httpx

output = Path(os.environ['APPDATA']) / 'PaperangP1' / 'idle-acceptance.json'
start = time.monotonic()
baseline = None
observations = 0
previous_uptime = 0
with httpx.Client(trust_env=False, timeout=10) as client:
    while True:
        try:
            status = client.get('http://127.0.0.1:8765/api/status').json()
            jobs = client.get('http://127.0.0.1:8765/api/jobs').json()
            signature = (status.get('transport'), tuple((j['id'], j['state']) for j in jobs))
            ready = (status.get('connected') and status.get('state') == 'ready'
                     and not status['queue']['printing'] and status['queue']['pending'] == 0
                     and status.get('power_down_time') == 0
                     and status.get('last_seen_age_s', 999) < 120)
            uptime = status.get('uptime_s') or 0
            if not ready or baseline != signature or uptime < previous_uptime:
                start = time.monotonic(); observations = 0
            baseline = signature
            previous_uptime = uptime
            observations += int(bool(ready))
            elapsed = round(time.monotonic() - start, 1)
            passed = ready and elapsed >= 1800 and observations >= 30
            record = {'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                      'state': 'passed' if passed else 'observing',
                      'idle_seconds': elapsed, 'observations': observations,
                      'status': status}
        except Exception as error:
            start = time.monotonic(); baseline = None; observations = 0
            record = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'state': 'interrupted', 'error': str(error)}
            passed = False
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        if passed: break
        time.sleep(60)
