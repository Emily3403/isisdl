#!/usr/bin/env python3
import sys

# This is my personal preference
sys.argv.extend(["-v", "-d", "55", "-n", "6"])

import isisdl.__main__ as __main__  # noqa: E402


def main():
    # This sets my personal preference to download
    __main__.main()


if __name__ == '__main__':
    main()
