"""Accounts for TRAVEL QUEST (standard library only).

AUTH_USERS environment variable format (entries separated by "~", no commas so gcloud is happy):
    name:HASH[:demo]~name2:HASH2
HASH looks like  pbkdf2-sha256-600000-<salt hex>-<hash hex>   (passwords are never stored in plain text).
Create it with:  python3 tools/make_users.py demo --demo  alice
"""
import hashlib, hmac, re, secrets

ITERATIONS = 600_000
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
# Letters/digits without look-alikes (0/O, 1/l/I) so generated passwords are easy to type.
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt if salt is not None else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2-sha256-%d-%s-%s" % (iterations, salt.hex(), dk.hex())


def verify_password(password, stored):
    try:
        algo, kind, it, salt_hex, hash_hex = stored.split("-")
        if algo != "pbkdf2" or kind != "sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(it))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def generate_password(n=16):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def parse_users(raw):
    """-> {name: {"hash": str, "demo": bool}}. Malformed entries are ignored (never crash the login page)."""
    users = {}
    for entry in (raw or "").split("~"):
        parts = entry.strip().split(":")
        if len(parts) not in (2, 3) or not NAME_RE.match(parts[0]):
            continue
        if len(parts) == 3 and parts[2] != "demo":
            continue
        users[parts[0].lower()] = {"hash": parts[1], "demo": len(parts) == 3}
    return users


# Verified against when the user name does not exist, so "no such user" and "wrong password" take equally long.
_DUMMY = hash_password("dummy-password-for-timing", salt=b"\x00" * 16)


def check_login(users, name, password):
    """Return the lowercase user name if the credentials are right, else None."""
    name = (name or "").strip().lower()[:64]
    u = users.get(name)
    ok = verify_password(password or "", u["hash"] if u else _DUMMY)
    return name if (u and ok) else None
