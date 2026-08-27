"""Print the DB_URL for a deployment path and environment, read from .env (gitignored, copied from .env.example).

usage: db_target.py <path> <env>
  local                 LOCAL_DB_URL, default the compose database on localhost
  vercel prod           VERCEL_PROD_DB_URL
  vercel staging        VERCEL_STAGING_DB_URL (the project; the database part is chosen per command)
Exits 2 with "not implemented" for a pair that has no URL reachable from this machine.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

LOCAL_DEFAULT = "postgresql+psycopg://gym_user:gym_user@localhost:5432/gym_backend"
NOT_IMPLEMENTED = {
    (
        "azure",
        "staging",
    ): "the Azure box has no URL reachable from here; use `just azure seed` in the gym root, which works over SSH",
    ("azure", "prod"): "production is EAShibby's box, reached only through Portainer",
}


def main(path: str, env: str) -> None:
    match (path, env):
        case ("local", ""):
            print(os.environ.get("LOCAL_DB_URL", LOCAL_DEFAULT))
        case ("vercel", "prod" | "staging" as e):
            key = f"VERCEL_{e.upper()}_DB_URL"
            url = os.environ.get(key)
            if not url:
                sys.exit(f"{key} is not set in .env")
            print(url)
        case pair if pair in NOT_IMPLEMENTED:
            sys.exit(f"not implemented: {NOT_IMPLEMENTED[pair]}")
        case _:
            sys.exit(
                f"unknown target {path} {env}: use `local`, `vercel prod` or `vercel staging`"
            )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
