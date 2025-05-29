from tomic.journal import update_margins
from tomic.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    update_margins.update_all_margins()
