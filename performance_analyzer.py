from tomic.analysis import performance_analyzer
import sys
from tomic.logging import setup_logging

setup_logging()

if __name__ == "__main__":
    performance_analyzer.main(sys.argv[1:])
