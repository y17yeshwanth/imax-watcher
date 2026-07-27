#!/usr/bin/env python3
"""
AMC Showtime Watcher - The Odyssey at AMC Metreon 16, Aug 22 2026

How detection works:
  AMC's showtimes are client-side rendered, so the initial HTML never
  contains the actual showtime times. What IS in the HTML is the
  "sorry, no showtimes found" message when nothing is scheduled.
  So: absence of that phrase = showtimes are live.

Run manually:       python3 check_showtimes.py
Test detection:     python3 check_showtimes.py --test
Install cron:       bash setup.sh
Remove cron:        bash setup.sh --remove
Re-arm after alert: rm ~/imax-watcher/.notified
"""

import logging
import subprocess
import sys
import os
import requests
from datetime import datetime

IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DATE     = "2026-08-22"
KNOWN_GOOD_DATE = "2026-08-19"   # already has showtimes — used by --test
THEATRE_SLUG    = "amc-metreon-16"
MOVIE_SLUG      = "the-odyssey-76238"

# ntfy.sh topic — subscribe to this in the ntfy app on your phone
NTFY_TOPIC = "ypacha-amc-metreon"

def make_url(date: str) -> str:
    return (
        f"https://www.amctheatres.com/movies/{MOVIE_SLUG}/showtimes"
        f"?date={date}&theatre={THEATRE_SLUG}"
    )

TARGET_URL = make_url(TARGET_DATE)

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
LOG_FILE      = os.path.join(SCRIPT_DIR, "watcher.log")
STATE_FILE    = os.path.join(SCRIPT_DIR, ".notified")   # delete to re-arm
RUN_COUNT_FILE = os.path.join(SCRIPT_DIR, ".run_count")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Notification ──────────────────────────────────────────────────────────────
def notify_ntfy(title: str, body: str, url: str) -> None:
    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode(),
            headers={
                "Title": title,
                "Priority": "urgent",
                "Tags": "movie_camera",
                "Click": url,
            },
            timeout=10,
        )
        resp.raise_for_status()
        log.info("ntfy notification sent.")
    except requests.RequestException as exc:
        log.error("ntfy notification failed: %s", exc)

def disable_workflow() -> None:
    """Disable this GitHub Actions workflow so it stops running after notifying."""
    repo     = os.environ.get("GH_REPO", "")
    workflow = os.environ.get("WORKFLOW_FILE", "amc-watcher.yml")
    try:
        subprocess.run(
            ["gh", "api", "--method", "PUT",
             f"/repos/{repo}/actions/workflows/{workflow}/disable"],
            check=True, capture_output=True,
        )
        log.info("GitHub Actions workflow disabled — no more checks will run.")
    except subprocess.CalledProcessError as exc:
        log.error("Failed to disable workflow: %s", exc.stderr.decode())

def alert(dry_run: bool = False) -> None:
    log.info("SHOWTIMES AVAILABLE — firing alert.")
    if not dry_run:
        notify_ntfy(
            title="AMC Metreon 16 — Book Now!",
            body="The Odyssey Aug 22 showtimes are LIVE! Tap to open booking page.",
            url=TARGET_URL,
        )
        if IN_CI:
            disable_workflow()
        else:
            with open(STATE_FILE, "w") as f:
                f.write(datetime.now().isoformat() + "\n")
    else:
        log.info("[DRY RUN] Would send ntfy notification.")

# ── Fetching ──────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Minimum page size we'll trust as a real AMC response (bot-block pages are tiny)
MIN_PAGE_BYTES = 100_000

NO_SHOWTIME_PHRASES = [
    "sorry, no showtimes found",
    "no showtimes found",
    "check this theatre again soon",
    "showtimes for friday and beyond are usually posted",
]

def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        log.error("Fetch failed: %s", exc)
        return None


def check_showtimes(url: str) -> bool:
    html = fetch_html(url)
    if not html:
        return False

    if len(html) < MIN_PAGE_BYTES:
        log.warning("Page too short (%d chars) — likely bot-blocked, skipping.", len(html))
        return False

    lower = html.lower()
    for phrase in NO_SHOWTIME_PHRASES:
        if phrase in lower:
            log.info("No showtimes yet (page contains '%s').", phrase)
            return False

    log.info("No 'no showtimes' message found in %d-char page — showtimes are live!", len(html))
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    test_mode = "--test" in sys.argv

    if test_mode:
        url = make_url(KNOWN_GOOD_DATE)
        log.info("TEST MODE: checking %s (should have showtimes)", url)
        if check_showtimes(url):
            log.info("TEST PASSED — detection works. Sending ntfy notification...")
            notify_ntfy(
                title="AMC Watcher test",
                body="ntfy is working! You'll get a phone ping when Aug 22 showtimes go live.",
                url=TARGET_URL,
            )
        else:
            log.error(
                "TEST FAILED — Aug 19 page not detected as having showtimes. "
                "Check your network or whether that date still has showtimes."
            )
        return

    if IN_CI:
        log.info("── GitHub Actions run ──────────────────")
    else:
        try:
            count = int(open(RUN_COUNT_FILE).read().strip()) + 1 if os.path.exists(RUN_COUNT_FILE) else 1
        except ValueError:
            count = 1
        with open(RUN_COUNT_FILE, "w") as f:
            f.write(str(count))
        log.info("── Run #%d ─────────────────────────────", count)

        if os.path.exists(STATE_FILE):
            log.info("Already notified. Delete %s to re-arm.", STATE_FILE)
            return

    log.info("Checking %s", TARGET_URL)
    available = check_showtimes(TARGET_URL)
    if available:
        log.info("Result: AVAILABLE ✓")
        alert()
    else:
        log.info("Result: not available yet. Next check in ~5 min.")

if __name__ == "__main__":
    main()
