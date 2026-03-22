#!/usr/bin/env python3
"""Monitor a tmux pane for Claude Code rate limits and auto-continue."""
import subprocess, re, sys, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
LIMIT_RE = re.compile(r'[Rr]esets?\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(([^)]+)\)')
POLL = 60
MARGIN = 60
VERBOSE = False  # set to True for debug output


def parse_reset(text):
    m = LIMIT_RE.search(ANSI_RE.sub('', text))
    if not m:
        return None
    h, ap, tz = int(m[1]), m[3].lower(), m[4]
    mi = int(m[2]) if m[2] else 0
    if ap == 'pm' and h != 12: h += 12
    if ap == 'am' and h == 12: h = 0
    try:
        zone = ZoneInfo(tz)
    except KeyError:
        zone = datetime.now().astimezone().tzinfo
    now = datetime.now(zone)
    target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if target < now - timedelta(hours=1):
        target += timedelta(days=1)
    return target


def send_continue(pane):
    run = lambda *a: subprocess.run(['tmux', 'send-keys', '-t', pane, *a], capture_output=True, timeout=5)
    run('Escape')
    time.sleep(0.1)
    run('continue', 'Enter')


def capture(pane):
    return subprocess.run(['tmux', 'capture-pane', '-t', pane, '-p'],
                         capture_output=True, text=True, timeout=5).stdout


def fg_is_claude(pane):
    fg = subprocess.run(['tmux', 'display-message', '-t', pane, '-p', '#{pane_current_command}'],
                       capture_output=True, text=True, timeout=5).stdout.strip().lower()
    return any(c in fg for c in ['claude', 'node'])


if __name__ == '__main__':
    pane = sys.argv[1] if len(sys.argv) > 1 else '%0'
    sent = False
    if VERBOSE: print(f'[monitor] Watching {pane}')

    while True:
        time.sleep(POLL)
        try:
            reset = parse_reset(capture(pane))
        except Exception:
            continue

        if not reset:
            if sent:
                if VERBOSE: print('[monitor] Rate limit cleared.')
            sent = False
            continue

        if sent:
            continue  # already sent continue for this rate limit

        wait = (reset - datetime.now(reset.tzinfo)).total_seconds() + MARGIN
        if wait > 0:
            if VERBOSE: print(f'[monitor] Rate limit. Reset {reset.strftime("%H:%M %Z")}. Waiting {int(wait)}s...')
            time.sleep(wait)

        if not parse_reset(capture(pane)):
            if VERBOSE: print('[monitor] Cleared while waiting.')
            continue
        if not fg_is_claude(pane):
            if VERBOSE: print('[monitor] Not Claude in foreground. Skipping.')
            continue

        send_continue(pane)
        sent = True
        if VERBOSE: print('[monitor] Sent continue.')
