"""
passwords.py — the staff password policy.

  * at least MIN_PASSWORD_LENGTH characters (default 10);
  * not one of the most common passwords, not built from the person's own
    email/name or "traytrack", not one repeated character or a keyboard run;
  * optionally (PWNED_PASSWORD_CHECK=1) not in a known breach, checked with
    the Have I Been Pwned k-anonymity API: only the first 5 characters of the
    password's SHA-1 leave the server, and a network failure never blocks a
    password change.
"""

import hashlib
import logging
import os
import urllib.request

logger = logging.getLogger("traytrack.passwords")

MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", "10"))
PWNED_CHECK = os.environ.get("PWNED_PASSWORD_CHECK", "0") == "1"

# The most common passwords in public breach lists (lower-cased), plus
# obvious local variants. Not exhaustive — the breach check is.
COMMON = {
    "123456", "123456789", "12345678", "1234567890", "password", "password1", "password123", "qwerty", "qwerty123",
    "qwertyuiop", "abc123", "111111", "123123", "1234567", "iloveyou", "admin", "admin123", "administrator",
    "welcome", "welcome1", "welcome123", "letmein", "monkey", "dragon", "football", "cricket", "baseball",
    "sunshine", "princess", "master", "shadow", "superman", "batman", "trustno1", "passw0rd", "p@ssw0rd",
    "p@ssword", "changeme", "changeme123", "default", "secret", "login", "starwars", "whatever", "freedom",
    "india123", "india@123", "bharat", "hello123", "computer", "internet", "zaq12wsx", "1q2w3e4r", "1q2w3e4r5t",
    "asdfghjkl", "asdf1234", "zxcvbnm", "qazwsx", "pass1234", "mess123", "messhall", "college123", "student123",
    "principal", "inspector", "fssai123", "food1234", "canteen123",
}
KEYBOARD_RUNS = ("1234567890", "0987654321", "qwertyuiop", "asdfghjkl", "zxcvbnm", "abcdefghijklmnopqrstuvwxyz")


def _pwned(password):
    """True if the password appears in a known breach (fail-open)."""
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    try:
        req = urllib.request.Request(f"https://api.pwnedpasswords.com/range/{sha1[:5]}",
                                     headers={"Add-Padding": "true", "User-Agent": "TrayTrack"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode()
    except Exception as e:
        logger.warning("Breach check unavailable, skipping: %s", e)
        return False
    return any(line.split(":")[0] == sha1[5:] and int(line.split(":")[1]) > 0
               for line in body.splitlines() if ":" in line)


def problem_with(password, email="", name=""):
    """A user-facing reason the password isn't acceptable, or None."""
    pw = password or ""
    low = pw.lower()
    if len(pw) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters — a short phrase is easiest to remember."
    if low in COMMON or low.rstrip("!@#$.0123456789") in COMMON:
        return "That's one of the most commonly used passwords. Choose something less predictable."
    if len(set(low)) <= 2:
        return "Use more than one or two different characters."
    if any(low in run or run[:len(low)] == low for run in KEYBOARD_RUNS):
        return "Keyboard or alphabet sequences are too easy to guess."
    personal = {p for p in ((email or "").split("@")[0].lower(), *(name or "").lower().split(), "traytrack") if len(p) >= 4}
    if any(p in low for p in personal):
        return "Don't build the password from your name, email or the app's name."
    if PWNED_CHECK and _pwned(pw):
        return "This password has appeared in a data breach. Choose a different one."
    return None
