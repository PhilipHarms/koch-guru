"""Create login keys for APP_USERS.

    python -m koch_guru.web.keys philip charlotte

prints the value for the Railway variable APP_USERS. Each person then opens
https://<app address>/login/<their key> once on every device.
"""

from __future__ import annotations

import secrets
import sys


def make_app_users(names: list[str]) -> str:
    return ",".join(f"{name.lower()}:{secrets.token_urlsafe(32)}" for name in names)


def main(argv: list[str]) -> int:
    if not argv:
        print("Aufruf: python -m koch_guru.web.keys philip charlotte", file=sys.stderr)
        return 2
    print(make_app_users(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
