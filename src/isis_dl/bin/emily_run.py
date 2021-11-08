#!/usr/bin/env python3
import sys

# A little hack in order to get the verbose to work
sys.argv.append("-v")

import isis_dl.__main__ as __main__  # noqa: E402
from isis_dl.share.utils import args  # noqa: E402


def main():
    # This sets my personal preference to download
    args.num_threads = 8
    args.num_threads_instantiate = 32
    args.download_rate = 55

    __main__.main()


if __name__ == '__main__':
    main()
