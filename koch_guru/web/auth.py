"""Login with a personal link per person, no passwords.

APP_USERS maps a long random key to a name. Opening /login/<key> stores the
key in an HTTP-only cookie; every API call checks that cookie. Replacing a key
on Railway signs that person out on all devices.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

COOKIE_NAME = "kg_session"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # one year


def user_for_key(users: dict[str, str], key: str | None) -> str | None:
    """Name of the user with this key. Compares every key in constant time."""
    if not key:
        return None
    found = None
    for known, name in users.items():
        if hmac.compare_digest(known.encode(), key.encode()):
            found = name
    return found


def current_user(request: Request) -> str:
    """FastAPI dependency: the signed-in user's name, else 401."""
    name = user_for_key(request.app.state.users, request.cookies.get(COOKIE_NAME))
    if name is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    return name


def display_name(name: str) -> str:
    return name[:1].upper() + name[1:]
