#!/usr/bin/env python3

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.utils import args, database_helper
from isisdl.bin.update import install_latest_version
from isisdl.settings import is_first_time
from isisdl.version import __version__
import isisdl.bin.config as config


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(__version__)
    exit(0)


def main() -> None:
    maybe_print_version_and_exit()
    install_latest_version()

    if is_first_time:
        print("It seams as if this is your first time executing isisdl. Welcome <3\n")
        config.main()
        print("\n\nIn the next version I will rediscover your files automatically.\nIf you have already run me before, press CTRL+C and run `isisdl-sync`.")
        # import isisdl.bin.sync_database as sync
        # print("Rediscovering your files ...")
        # sync.main()
        print("\n\nI am now starting to download your files ...\n")

    user = get_credentials()

    dl = CourseDownloader(user)

    dl.start()

    print("\nDone! Have a nice day ^.^")


# TODO:
#   Autolog to server
#   H265
#
#   Maybe systemd timer


if __name__ == "__main__":
    database_helper.get_state()
    main()
