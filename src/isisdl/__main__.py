#!/usr/bin/env python3
import sys

import isisdl.compress as compress
from isisdl.backend import sync_database
from isisdl.backend.config import init_wizard, config_wizard
from isisdl.backend.request_helper import CourseDownloader
from isisdl.settings import is_first_time, is_static, forbidden_chars, has_ffmpeg, fstype, is_windows, working_dir_location, python_executable, is_macos
from isisdl.settings import is_online
from isisdl.utils import args, acquire_file_lock_or_exit, generate_error_message, install_latest_version, export_config, database_helper, \
    config, migrate_database, Config
from isisdl.version import __version__


def print_version() -> None:
    print(f"""isisdl version {__version__}

Running on {"MacOS" if is_macos else "Windows" if is_windows else "Linux"}
This is {"" if is_static else "not"} the compiled version

working directory: {working_dir_location}
python executable: {python_executable}

database_version = {Config.default("database_version")}
{has_ffmpeg = }
{forbidden_chars = }
{fstype = }
""")


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
            sys.exit(1)

        sys.exit(0)

    elif args.version:
        print_version()
        sys.exit(0)

    acquire_file_lock_or_exit()

    if args.init:
        init_wizard()
        sys.exit(0)

    elif args.config:
        config_wizard()
        sys.exit(0)

    elif not is_windows and args.export_config:
        print("Exporting current configuration ...")
        export_config()
        sys.exit(0)

    elif args.delete_bad_urls:
        print("Deleting bad urls ...")
        database_helper.delete_bad_urls()
        sys.exit(0)

    if not is_online:
        print("I cannot establish an internet connection.")
        sys.exit(1)

    install_latest_version()

    if args.update:
        print("No new update available ... (cricket sounds)")
        sys.exit(0)

    elif args.sync:
        sync_database.main()
        sys.exit(0)

    elif args.compress:
        compress.main()
        sys.exit(0)

    elif args.subscribe:
        print("Due to legal reasons, this is currently not supported. :(")
        sys.exit(0)

    #         print("""Attention:
    # This option will lead to you subscribing to *every* publicly available ISIS course.
    #
    # Subscribing will be quite fast 10-20s, but unsubscribing takes a few minutes.
    # This behaviour is due to the fact that the API to unsubscribe from courses
    # is not yet implemented. (https://tracker.moodle.org/browse/MDL-64255)
    #
    # Please press enter to continue.
    # """)
    #
    #         input()
    #         subscribe_to_all_courses()
    #         sys.exit(0)

    elif args.unsubscribe:
        print("Due to legal reasons, this is currently not supported. :(")
        sys.exit(0)

        # unsubscribe_from_courses()
        # sys.exit(0)

    else:
        # Main routine
        CourseDownloader().start()
        print("\nDone! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception as ex:
        generate_error_message(ex)


# Feature discussion:
#   Windows autorun
#   Download of corrupted files


# Suggestion for ISIS API:
#   video server also sends the size

# Main TODOS:
#   Dynamic calculation of num threads for download
#   fixing / bug hunting the compress


# No size implies:
#   More time conflicts in video files (File size from 10^9 → 10^4)
#   No download status file size
#   No sync database


# TODO: Isis display name change

# TODO: static builds from github runners

# TODO: change settings to posix / linux and do things accordingly.

# TODO: Throttling does not work when imposed via config ??

# TODO: Argcomplete https://pypi.org/project/argcomplete/
#  qmk can also do this

# TODO: Wiki tutorial for streaming. It is *really* easy

# TODO Stream: Is it problematic if the download doesnt continue for a short / long time?

# TODO: Catch the bandwidth-small-error bug

# TODO: Test if export config being dynamic leads to problems on windows


# TODO with D-VA: How problematic is WZM?


if __name__ == "__main__":
    main()
