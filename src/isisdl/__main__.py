#!/usr/bin/env python3

import isisdl.compress as compress
from isisdl.backend import sync_database
from isisdl.backend.config import init_wizard, config_wizard
from isisdl.backend.request_helper import CourseDownloader
from isisdl.settings import is_first_time
from isisdl.settings import is_online
from isisdl.utils import args, acquire_file_lock_or_exit, generate_error_message, subscribe_to_all_courses, unsubscribe_from_courses, install_latest_version, export_config, database_helper, \
    config, migrate_database
from isisdl.version import __version__


def _main() -> None:
    if is_first_time:
        print("""
It seems as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read these options carefully.

If you wish to re-configure me, run `isisdl --init` or `isisdl --config`.


Please press enter to continue.
""")
        input()
        init_wizard()
        config_wizard()
        sync_database.main()

    elif database_helper.get_database_version() < config.default("database_version"):
        if migrate_database() is False:
            exit(1)

        exit(0)

    elif args.version:
        print(f"isisdl Version {__version__}")
        exit(0)

    acquire_file_lock_or_exit()

    if args.init:
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
        exit(0)

    elif args.compress:
        compress.main()
        exit(0)

    elif args.subscribe:
        print("""Attention:
This option will lead to you subscribing to *every* publicly available ISIS course.

Subscribing will be quite fast < 1min, but unsubscribing takes a long time.
This behaviour is due to the fact that the API to unsubscribe from courses
is not yet implemented. (https://tracker.moodle.org/browse/MDL-64255)

Please press enter to continue.
""")

        input()
        subscribe_to_all_courses()
        exit(0)

    elif args.unsubscribe:
        unsubscribe_from_courses()
        exit(0)

    else:
        # Main routine
        CourseDownloader().start()
        print("Done! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception as ex:
        generate_error_message(ex)


# TODO:
#   Use mp4 metadata to recognize files
#   Subscribe to *all* courses
#   When using --config the password seams to be reset
#   Whitelisting doesn't work?

# TODO:
#   How to speed things up
#       Check online → check latest version
#       Check latest version → threads
#       When discovering have 64 threads that do the lifting + 32 max for every hostname
#       Maybe make download_videos own thread again

#       → More threads!


# Feature discussion:
#   Windows autorun
#   Download of corrupted files
#   Streaming files: Is it worth it?

if __name__ == "__main__":
    main()
