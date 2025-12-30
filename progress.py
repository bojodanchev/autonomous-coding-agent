"""
Progress Tracking Utilities
===========================

Functions for tracking and displaying progress of the autonomous coding agent.
"""

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path


WEBHOOK_URL = os.environ.get("PROGRESS_N8N_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROGRESS_CACHE_FILE = ".progress_cache"
TELEGRAM_MILESTONE_INTERVAL = 10  # Notify every N completed features


def send_telegram_notification(message: str) -> bool:
    """
    Send a notification via Telegram bot.

    Args:
        message: The message to send

    Returns:
        True if sent successfully, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[Telegram notification failed: {e}]")
        return False


def check_telegram_milestone(passing: int, previous: int, total: int, project_dir: Path, completed_tests: list) -> None:
    """
    Check if we've hit a milestone (every 10 features) and send Telegram notification.

    Args:
        passing: Current number of passing tests
        previous: Previous number of passing tests
        total: Total number of tests
        project_dir: Project directory name
        completed_tests: List of newly completed test descriptions
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    # Calculate which milestones we've crossed
    previous_milestone = (previous // TELEGRAM_MILESTONE_INTERVAL) * TELEGRAM_MILESTONE_INTERVAL
    current_milestone = (passing // TELEGRAM_MILESTONE_INTERVAL) * TELEGRAM_MILESTONE_INTERVAL

    # Check if we crossed a new milestone
    if current_milestone > previous_milestone:
        percentage = round((passing / total) * 100, 1) if total > 0 else 0

        # Build the message
        message = (
            f"🎯 <b>Milestone Reached!</b>\n\n"
            f"📊 <b>Project:</b> {project_dir.name}\n"
            f"✅ <b>Progress:</b> {passing}/{total} tests ({percentage}%)\n"
            f"🏆 <b>Milestone:</b> {current_milestone} features completed!\n\n"
        )

        # Add recently completed tests (last 5 max to keep message short)
        if completed_tests:
            recent = completed_tests[-5:] if len(completed_tests) > 5 else completed_tests
            message += "📝 <b>Recently completed:</b>\n"
            for test in recent:
                # Truncate long descriptions
                desc = test[:60] + "..." if len(test) > 60 else test
                message += f"  • {desc}\n"

        message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        send_telegram_notification(message)


def send_progress_webhook(passing: int, total: int, project_dir: Path) -> None:
    """Send webhook notification and Telegram milestone alerts when progress increases."""
    cache_file = project_dir / PROGRESS_CACHE_FILE
    previous = 0
    previous_passing_tests = set()

    # Read previous progress and passing test indices
    if cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text())
            previous = cache_data.get("count", 0)
            previous_passing_tests = set(cache_data.get("passing_indices", []))
        except:
            previous = 0

    # Only notify if progress increased
    if passing > previous:
        # Find which tests are now passing
        tests_file = project_dir / "feature_list.json"
        completed_tests = []
        current_passing_indices = []

        if tests_file.exists():
            try:
                with open(tests_file, "r") as f:
                    tests = json.load(f)
                for i, test in enumerate(tests):
                    if test.get("passes", False):
                        current_passing_indices.append(i)
                        if i not in previous_passing_tests:
                            # This test is newly passing
                            desc = test.get("description", f"Test #{i+1}")
                            category = test.get("category", "")
                            if category:
                                completed_tests.append(f"[{category}] {desc}")
                            else:
                                completed_tests.append(desc)
            except:
                pass

        # Send Telegram notification if milestone reached (every 10 features)
        check_telegram_milestone(passing, previous, total, project_dir, completed_tests)

        # Send n8n webhook if configured
        if WEBHOOK_URL:
            payload = {
                "event": "test_progress",
                "passing": passing,
                "total": total,
                "percentage": round((passing / total) * 100, 1) if total > 0 else 0,
                "previous_passing": previous,
                "tests_completed_this_session": passing - previous,
                "completed_tests": completed_tests,
                "project": project_dir.name,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            try:
                req = urllib.request.Request(
                    WEBHOOK_URL,
                    data=json.dumps([payload]).encode('utf-8'),  # n8n expects array
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                print(f"[Webhook notification failed: {e}]")

        # Update cache with count and passing indices
        cache_file.write_text(json.dumps({
            "count": passing,
            "passing_indices": current_passing_indices
        }))
    else:
        # Update cache even if no change (for initial state)
        if not cache_file.exists():
            tests_file = project_dir / "feature_list.json"
            current_passing_indices = []
            if tests_file.exists():
                try:
                    with open(tests_file, "r") as f:
                        tests = json.load(f)
                    for i, test in enumerate(tests):
                        if test.get("passes", False):
                            current_passing_indices.append(i)
                except:
                    pass
            cache_file.write_text(json.dumps({
                "count": passing,
                "passing_indices": current_passing_indices
            }))


def count_passing_tests(project_dir: Path) -> tuple[int, int]:
    """
    Count passing and total tests in feature_list.json.

    Args:
        project_dir: Directory containing feature_list.json

    Returns:
        (passing_count, total_count)
    """
    tests_file = project_dir / "feature_list.json"

    if not tests_file.exists():
        return 0, 0

    try:
        with open(tests_file, "r") as f:
            data = json.load(f)

        # Handle both flat array and wrapped object formats
        if isinstance(data, list):
            tests = data
        elif isinstance(data, dict) and "features" in data:
            tests = data["features"]
        else:
            tests = []

        total = len(tests)
        passing = sum(1 for test in tests if isinstance(test, dict) and test.get("passes", False))

        return passing, total
    except (json.JSONDecodeError, IOError):
        return 0, 0


def print_session_header(session_num: int, is_initializer: bool) -> None:
    """Print a formatted header for the session."""
    session_type = "INITIALIZER" if is_initializer else "CODING AGENT"

    print("\n" + "=" * 70)
    print(f"  SESSION {session_num}: {session_type}")
    print("=" * 70)
    print()


def print_progress_summary(project_dir: Path) -> None:
    """Print a summary of current progress."""
    passing, total = count_passing_tests(project_dir)

    if total > 0:
        percentage = (passing / total) * 100
        print(f"\nProgress: {passing}/{total} tests passing ({percentage:.1f}%)")
        send_progress_webhook(passing, total, project_dir)
    else:
        print("\nProgress: feature_list.json not yet created")
