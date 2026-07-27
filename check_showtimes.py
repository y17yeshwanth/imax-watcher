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
Re-arm after alert: rm ~/imax-watcher/.notified
"""

import logging
import sys
import os
import requests
from datetime import datetime

IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DATE     = "2026-08-22"
KNOWN_GOOD_DATE = "2026-08-19"
THEATRE_SLUG    = "amc-metreon-16"
MOVIE_SLUG      = "the-odyssey-76238"

NTFY_TOPIC = "ypacha-amc-metreon"

def make_url(date: str) -> str:
    return (
        f"https://www.amctheatres.com/movies/{MOVIE_SLUG}/showtimes"
        f"?date={date}&theatre={THEATRE_SLUG}"
    )

TARGET_URL = make_url(TARGET_DATE)

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
LOG_FILE       = os.path.join(SCRIPT_DIR, "watcher.log")
STATE_FILE     = os.path.join(SCRIPT_DIR, ".notified")
RUN_COUNT_FILE = os.path.join(SCRIPT_DIR, ".run_count")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE) if not IN_CI else logging.StreamHandler(sys.stdout),
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

def set_gha_output(key: str, value: str) -> None:
    """Signal to the workflow that showtimes were found — stops the self-trigger chain."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")

def alert(dry_run: bool = False) -> None:
    log.info("SHOWTIMES AVAILABLE — firing alert.")
    if not dry_run:
        notify_ntfy(
            title="AMC Metreon 16 — Book Now!",
            body="The Odyssey Aug 22 showtimes are LIVE! Tap to open booking page.",
            url=TARGET_URL,
        )
        if IN_CI:
            set_gha_output("found", "true")
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
        log.warning("Page too short (%d chars) — likely bot-blocked.", len(html))
        return False
    lower = html.lower()
    for phrase in NO_SHOWTIME_PHRASES:
        if phrase in lower:
            log.info("No showtimes yet ('%s' found in page).", phrase)
            return False
    log.info("Showtimes are live! (%d-char page, no 'no showtimes' message)", len(html))
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    test_mode = "--test" in sys.argv

    if test_mode:
        url = make_url(KNOWN_GOOD_DATE)
        log.info("TEST MODE: checking %s", url)
        if check_showtimes(url):
            log.info("TEST PASSED — sending ntfy notification...")
            notify_ntfy(
                title="AMC Watcher test",
                body="ntfy is working! You'll get a ping when Aug 22 showtimes go live.",
                url=TARGET_URL,
            )
        else:
            log.error("TEST FAILED — Aug 19 showtimes not detected.")
        return

    if not IN_CI:
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
    if check_showtimes(TARGET_URL):
        log.info("Result: AVAILABLE ✓")
        alert()
    else:
        log.info("Result: not available yet.")

if __name__ == "__main__":
    main()
