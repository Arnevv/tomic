from tomic.journal import update_margins
from tomic.logging import logger, setup_logging

if __name__ == "__main__":
    setup_logging()
    logger.info("🚀 Margins updaten")
    update_margins.update_all_margins()
