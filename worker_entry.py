"""standalone entry point for the auto-sync worker process."""

import sys

from worker.run import main

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
