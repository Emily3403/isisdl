#!/usr/bin/env python3
from http.client import HTTPSConnection

import isisdl.bin.sync_database as sync_database
import isisdl.bin.compress as compress

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.utils import args, acquire_file_lock_or_exit, generate_error_message, subscribe_to_all_courses, unsubscribe_from_courses, database_helper, install_latest_version, \
    generate_current_config_str, export_config
from isisdl.bin.config import init_wizard, config_wizard
from isisdl.settings import is_first_time, export_config_file_location
from isisdl.version import __version__

from isisdl.settings import is_online


def _main() -> None:
    if is_first_time:
        print(f"""
It seems as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read the options carefully.

If you wish to re-configure me run `isisdl --init` or `isisdl --config`.


Please press enter to continue.
""")
        input()
        init_wizard()
        config_wizard()
        sync_database._main()

    elif args.version:
        print(f"isisdl Version {__version__}")
        exit(0)

    elif args.init:
        init_wizard()
        exit(0)

    elif args.config:
        config_wizard()
        exit(0)

    elif args.export_config:
        print("Exporting current configuration ...")
        export_config()
        exit(0)

    if not is_online:
        print("I cannot establish an internet connection.")
        exit(1)

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
#   Better support for streaming
#   Subscribe to *all* courses

# Future todos:
#   Installer for windows with autorun


if __name__ == "__main__":
    main()
