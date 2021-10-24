#!/usr/bin/env python3
import warnings

from bs4 import GuessedAtParserWarning

from isis_dl.backend.api import CourseDownloader
from isis_dl.backend.crypt import get_credentials
from isis_dl.bin import call_all
from isis_dl.share.utils import on_kill, logger

warnings.filterwarnings('ignore', category=GuessedAtParserWarning)


def main():
    call_all()

    user = get_credentials()

    dl = CourseDownloader(user)

    @on_kill(2)
    def goodbye():
        logger.info("Storing checksums…")
        dl.finish()
        logger.info("Done! Bye Bye ^.^")

    dl.start()


# TODO:

#   TL;DR of how password storing works
#
#   Better checksum → include file size + other metadata?
#   Really dynamic calculation of checksum based on the first 64, 512, … bytes → is this too much overhead?
#
#   URI Decode
#
#   Automatic upload to PyPi: https://www.caktusgroup.com/blog/2021/02/11/automating-pypi-releases/
#
#   Check for corrupted files

# Maybe todo

#   Add rate limiter
#
#   Change instantiation of MediaContainer into web-requests + multiprocessing. Should be more efficient - but is fast enough already


# Changelog:
#
# Version 0.2
#   Changed downloading mechanism from
#       Have a ThreadPoolExecutor for each course which downloads with args.num_threads
#   to
#       Have a ThreadPoolExecutor which goes over instantiated objects
#
#   `random.shuffle(…)`-s the input data → better download efficiency
#
#   When interrupted → Robustly finish current downloads (Intercepts everything except SIGKILL)
#       When prompted again will exit with `os._exit(1)` and skip all cleanup
#
#   Better status indicator
#
#   Moved auto-unzip to manual-unzip
#
#   Faster instantiation of MediaContainer's
#


if __name__ == '__main__':
    main()
