#!/usr/bin/env python3
from http.client import HTTPSConnection

import isisdl.bin.sync_database as sync_database
import isisdl.bin.compress as compress

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.update import install_latest_version
from isisdl.backend.utils import args, acquire_file_lock_or_exit, generate_error_message, subscribe_to_all_courses, unsubscribe_from_courses
from isisdl.bin.config import run_config_wizard, isis_config_wizard
from isisdl.settings import is_first_time
from isisdl.version import __version__


def print_version_and_exit() -> None:
    print(f"isisdl Version {__version__}")
    exit(0)


def check_online() -> None:
    # Copied from https://stackoverflow.com/a/29854274
    conn = HTTPSConnection("8.8.8.8", timeout=5)
    try:
        conn.request("HEAD", "/")
        return
    except Exception:
        print("I cannot establish an internet connection.")
        exit(1)
    finally:
        conn.close()


def _main() -> None:
    if args.version:
        print_version_and_exit()
        exit(0)

    elif args.init:
        run_config_wizard()
        exit(0)

    elif args.config:
        isis_config_wizard()
        exit(0)

    # Now only routines follow that need the ISIS online database
    check_online()
    install_latest_version()

    if args.sync:
        sync_database.main()

    elif args.compress:
        compress.main()

    elif args.subscribe:
        subscribe_to_all_courses()

    elif args.unsubscribe:
        unsubscribe_from_courses()

    else:
        # Main routine
        acquire_file_lock_or_exit()

        if is_first_time:
            print("""It seems as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read the options carefully.
If you wish to re-configure me run `isisdl-config`.

If you think this is a mistake, click yourself through the wizard
and I will rediscover your files afterwards.

Please press enter to continue.""")
            input()
            run_config_wizard()
            sync_database._main()

    dl = CourseDownloader(get_credentials())

    dl.start()

    print("\n\nDone! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception:
        generate_error_message()


# TODO:
#   Use mp4 metadata to recognize files
#   Have only the executable `isisdl` with options

# Future todos:
#   Installer for windows with autorun


if __name__ == "__main__":
    main()
