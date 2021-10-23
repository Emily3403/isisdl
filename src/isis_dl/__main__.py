#!/usr/bin/env python3
import os
import warnings

from bs4 import GuessedAtParserWarning

from isis_dl.backend.api import CourseDownloader
from isis_dl.backend.crypt import get_credentials
from isis_dl.bin import call_all
from isis_dl.share.settings import blacklist_file_name_location, download_dir_location, temp_dir_location, intern_dir_location, password_dir, whitelist_file_name_location, settings_file_location, \
    course_name_to_id_file_location, log_dir_location
from isis_dl.share.utils import path, on_kill, logger

warnings.filterwarnings('ignore', category=GuessedAtParserWarning)


def startup():
    def prepare_dir(p):
        os.makedirs(path(p), exist_ok=True)

    def prepare_file(p):
        if not os.path.exists(path(p)):
            with open(path(p), "w"):
                pass

    def create_link_to_settings_file(file: str):
        fp = path(settings_file_location)

        def restore_link():
            os.symlink(file, fp)

        if os.path.exists(fp):
            if os.path.realpath(fp) != file:
                os.remove(fp)
                restore_link()
        else:
            restore_link()

    prepare_dir(download_dir_location)
    prepare_dir(temp_dir_location)
    prepare_dir(intern_dir_location)
    prepare_dir(password_dir)
    prepare_dir(log_dir_location)

    prepare_file(course_name_to_id_file_location)

    create_link_to_settings_file(os.path.abspath(__file__))
    prepare_file(whitelist_file_name_location)
    prepare_file(blacklist_file_name_location)


def main():
    startup()

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
#


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
