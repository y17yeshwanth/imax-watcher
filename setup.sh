#!/bin/bash
# Sets up a cron job to check AMC showtimes every 5 min, 24/7.
# Run once: bash setup.sh
# To remove: bash setup.sh --remove

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
JOB="*/5 * * * * $PYTHON $SCRIPT_DIR/check_showtimes.py >> $SCRIPT_DIR/watcher.log 2>&1"
MARKER="check_showtimes.py"

remove_job() {
    crontab -l 2>/dev/null | grep -v "$MARKER" | crontab -
    echo "Cron job removed."
}

if [[ "$1" == "--remove" ]]; then
    remove_job
    exit 0
fi

# Install if not already present
if crontab -l 2>/dev/null | grep -q "$MARKER"; then
    echo "Cron job already installed:"
    crontab -l | grep "$MARKER"
else
    (crontab -l 2>/dev/null; echo "$JOB") | crontab -
    echo "Cron job installed: runs every 5 min, 24/7."
    crontab -l | grep "$MARKER"
fi

echo ""
echo "Test run now? (runs the check once immediately)"
read -r -p "[y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    "$PYTHON" "$SCRIPT_DIR/check_showtimes.py"
fi
