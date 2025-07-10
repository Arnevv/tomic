from datetime import datetime, date
import os


def today() -> date:
    """Return ``TOMIC_TODAY`` or today's date."""
    env = os.getenv("TOMIC_TODAY")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    return date.today()
