import os
from datetime import datetime, timezone, date


def today() -> date:
    """Return TOMIC_TODAY or today's UTC date."""
    env = os.getenv("TOMIC_TODAY")
    return datetime.strptime(env, "%Y-%m-%d").date() if env else datetime.now(timezone.utc).date()
