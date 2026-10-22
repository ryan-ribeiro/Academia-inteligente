"""Complete schema migration and knowledge initialization before accepting requests."""

import subprocess
import sys

# Alembic runs separately; seeding needs its own registration of the client FK target.
from app.modules.clients import models as client_models  # noqa: F401
from app.modules.identity.demo_accounts import main as seed_demo_accounts
from app.modules.knowledge.bootstrap import main as seed_knowledge


def main() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    seed_demo_accounts()
    seed_knowledge()


if __name__ == "__main__":
    main()
