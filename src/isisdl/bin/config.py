#!/usr/bin/env python3
import os
import subprocess
import sys
from getpass import getpass
from typing import List, Optional, Union, Set, Dict, Any

import math
import yaml
from colorama import Style

from isisdl.backend.crypt import get_credentials, store_user
from isisdl.backend.downloads import SessionWithKey
from isisdl.backend.request_helper import RequestHelper
from isisdl.backend.utils import get_input, User, clear, config, error_text, generate_current_config_str, on_kill, run_cmd_with_error, acquire_file_lock_or_exit, remove_systemd_timer, logger, \
    install_systemd_timer
from isisdl.settings import is_windows, is_autorun, timer_file_location, service_file_location, export_config_file_location, working_dir_location

from isisdl.settings import is_online

was_in_configuration = False


def stored_prompt(prev: Any, allowed: Set[str]) -> None:
    if prev is None:
        return

    allowed.add("s")
    print("\n    [s] Use the stored option ", end="")

    if isinstance(prev, bool):
        print("Yes." if prev else "No")

    elif isinstance(prev, str):
        print(f"`{User.sanitize_name(prev)}`")

    else:
        print(f"`{prev}`")

    print()


def bool_prompt(name: str) -> Optional[bool]:
    # Will return None iff [s] is selected.

    prev = config.user(name)
    default: Optional[bool] = config.default(name)

    assert default is None or isinstance(default, bool)

    print(f"""
    [0] No{'  [default]' if default is False else ''}

    [1] Yes{'  [default]' if default is True else ''}
""")

    allowed = {"0", "1"}
    if default is not None:
        allowed.add("")

    stored_prompt(prev, allowed)
    choice = get_input(allowed)

    print()
    if choice == "s":
        return None
    elif choice == "":
        value = default
    else:
        value = bool(int(choice))

    setattr(config, name, value)

    return value


def authentication_prompt() -> None:
    clear()
    print("""Do you wish to store your password?

    [0] No

    [1] Yes  [default]
""")

    allowed = {"0", "1", ""}

    stored_prompt(config.user("username"), allowed)
    inp = get_input(allowed)

    if inp == "s":
        return
    elif inp == "":
        choice = True
    else:
        choice = bool(int(inp))

    if choice is False:
        config.username = None
        config.password = None
        config.password_encrypted = None
        return

    while True:
        print("Please provide your authentication for ISIS.")
        username = input("Username: ")
        password = getpass("Password: ")

        print("\nChecking if the password works ...")
        user = User(username, password)
        if SessionWithKey.from_scratch(user) is not None:
            print("ISIS accepted the password.")
            break

        print("ISIS does not accept the username / password. Please try again!\n")

    print()
    while True:
        additional_passphrase = getpass("Enter passphrase (empty for no passphrase): ")
        second = getpass("Enter same passphrase again: ")
        if additional_passphrase == second:
            break
        else:
            print("The passphrases do not match. Try again.\n")

    store_user(user, additional_passphrase)


def filename_prompt() -> None:
    clear()
    if is_windows:
        forbidden_chars = "<>:\"/\\|?*"
    else:
        forbidden_chars = "/"

    print(f"""Some programs / programming languages have restrictions or
inconveniences when it comes to working with special characters.

To combat this you can enable a {Style.BRIGHT}safe-mode for file names and paths{Style.RESET_ALL}.
If enabled, only ASCII letters + digits + "." are permitted as filenames.

In order to maintain the readability of filenames,
the next character after a whitespace is capitalized.

For example:
"I am / a \\ wierd 🐧 [filename].png" → "IAmAWierdFilename.png"


--- Note ---
The character{'s' if is_windows else ''} `{forbidden_chars}` {'are' if is_windows else 'is'} always replaced (not supported on a filesystem level).

When changing this option every file will be re-downloaded.
------------
""")
    bool_prompt("filename_replacing")


def throttler_prompt() -> None:
    clear()
    print("""Do you want to enable a limit for you download speed?


--- Note ---
You may overwrite this option by setting the `-d, --download-rate` flag.
------------


    [0] No  [default]

    [1] Only impose a limit for when `isisdl` automatically runs

    [2] Yes
""")
    allowed = {"0", "1", "2", ""}

    if config.user("throttle_rate") is not None or config.user("throttle_rate_autorun") is not None:
        allowed.add("s")
        store_str = "\n    [s] Use the stored option"
        if config.user("throttle_rate") == -1 and config.user("throttle_rate_autorun") == -1:
            store_str += " No"

        if config.user("throttle_rate") not in {-1, None}:
            store_str += f" {config.user('throttle_rate')} MiB/s (global)"

        if config.user("throttle_rate_autorun") not in {-1, None}:
            store_str += f" {config.user('throttle_rate_autorun')} MiB/s (autorun)"

        print(store_str)

    choice = get_input(allowed)

    if choice == "s":
        return

    if choice == "" or choice == "0":
        config.throttle_rate = -1
        config.throttle_rate_autorun = -1
        return

    if choice == "1":
        config_str = "throttle_rate_autorun"
    else:
        config_str = "throttle_rate"

    while True:
        print()
        try:
            amount = int(input("How many MiB/s am I allowed to consume? "))
            if amount < 1:
                raise ValueError("The number must be positive.")
            break

        except ValueError as ex:
            print(f"\n{error_text} Parsing the number failed.\nReason: {ex}\n")

    setattr(config, config_str, amount)


def timer_prompt() -> None:
    clear()

    print(f"""[Linux exclusive]
    
Do you want me to install a systemd timer to run `isisdl` every hour?

If you enable this option all new files will automagically appear in
`{working_dir_location}`
and you will never have to execute `isisdl` manually again.""")

    if is_windows:
        print(f"""

{error_text} It seems as if you are running Windows.

Automatic running `isisdl` is not supported.
If there is enough demand, I may implement this feature at some point.

Please press enter to continue
    """)
        input()
        return

    try:
        subprocess.check_call(["systemctl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print(f"""

{error_text} I cannot find the `systemctl` executable. 

My best guess is that you do not run a distro, which is based on systemd.
In that case this feature is not supported on your system.

If you do have systemd installed, please submit a bug-report at
https://github.com/Emily3403/isisdl/issues

Press enter to continue.""")
        logger.message("Systemd not installed")
        input()
        return

    print(f"""
--- Note ---
The configuration file for the timer is located at
`{timer_file_location}`,
if you want to tune the time manually
------------
""")

    choice = bool_prompt("timer_enable")

    if not choice:
        remove_systemd_timer()
    else:
        if config.user("password_encrypted"):
            print(f"""
{error_text} I cannot run `isisdl` automatically if the password is encrypted.

Do you wish to store the password unencrypted?

    [0] No

    [1] Yes
""")
            choice = bool(int(get_input({"0", "1"})))

            if choice is False:
                print("\nI am not installing the timer.")
                print("\nPlease press enter to continue\n")
                input()
                return

            else:
                user = get_credentials()
                store_user(user)
                print("The password is now stored unencrypted.")
                print("\nPlease press enter to continue\n")
                input()

        install_systemd_timer()


def telemetry_data_prompt() -> None:
    clear()
    print("""In order to ensure that all courses and files are downloaded correctly I would like
to collect some metadata from your courses, setup and configuration of isisdl.

I've previously relied on assertions and users reporting these assertions on github.
This system is really inconvenient for both parties and wastes a lot of time.

If you allow it, the program `isisdl` will automatically contact a server when it can report something.
""")
    bool_prompt("telemetry_policy")


def update_policy_prompt() -> None:
    clear()
    print("""Do you want me to auto-install updates when available?

The version on github is by design always more recent than the one on pip.
It should have no stability issues since the update is only ever installed,
if it passes all of the tests.

The version on pip should be always working and with no issues.
It is usually pushed a few days after the github release.


    [0] No

    [1] Install from pip  [default]

    [2] Install from github

    [3] Notify me when an update is available on pip

    [4] Notify me when an update is available on github
""")
    # TODO: static support: More options

    allowed = {"", "0", "1", "2", "3", "4"}

    stored_prompt(config.user("update_policy"), allowed)
    choice: Optional[str] = get_input(allowed)

    if choice == "s":
        return

    elif choice == "0":
        choice = None
    elif choice == "1" or choice == "":
        choice = "install_pip"
    elif choice == "2":
        choice = "install_github"
    elif choice == "3":
        choice = "notify_pip"
    else:
        choice = "notify_github"

    config.update_policy = choice


def _list_prompt(is_whitelist: bool) -> Union[List[int], bool]:
    clear()
    check_list = config.whitelist if is_whitelist else config.blacklist
    print(f"""Do you wish to {'whitelist' if is_whitelist else 'blacklist'} any of your courses?


    [0] No  [default]

    [1] Yes
""")
    # TODO: Why no bool prompt?

    allowed = {"", "0", "1"}
    if check_list is not None:
        print(f"\n    [s] Use the stored option {sorted(check_list)}")
        allowed.add("s")

    choice = get_input(allowed)
    if choice == "s":
        return True

    if choice == "0" or choice == "":
        return False

    if choice == "1" and not is_online:
        print("\nSince you are offline I am unable to retrieve the required information.\nPress enter to continue.\n")
        input()
        return True

    if RequestHelper._instance is None:
        print("\n(Getting information about courses ...)\n")

    user = get_credentials()
    helper = RequestHelper(user)
    courses = helper._courses
    if not courses:
        print("No courses available ...   (cricket sounds)")
        input()
        return True

    print("Please provide a comma-seperated list of the course-numbers.\nE.g. \"0, 2, 3\"\n")

    max_len = math.ceil(math.log(len(courses), 10))
    for i, course in enumerate(courses):
        print(f"    [{i}]{' ' * (max_len - len(str(i)))}   {course.name}")

    print()
    while True:
        user_input = input()
        try:
            lst = [int(item) for item in user_input.split(",")]
            if not all(0 <= item < len(courses) for item in lst):
                raise ValueError("Your input was not constrained to the listed choices.")

            break

        except Exception as ex:
            print(f"\nI did not quite catch that:\n{ex}\n")

    return [courses[i].course_id for i in lst]


def whitelist_prompt() -> None:
    lst = _list_prompt(True)
    if lst is True:
        return

    if lst is False:
        config.whitelist = None
        return

    assert isinstance(lst, list)

    config.whitelist = lst

    # Reevaluate courses
    user = get_credentials()
    RequestHelper(user).get_courses()


def blacklist_prompt() -> None:
    lst = _list_prompt(False)
    if lst is True:
        return

    if lst is False:
        config.blacklist = None
        return

    assert isinstance(lst, list)
    config.blacklist = lst

    # Reevaluate courses
    user = get_credentials()
    RequestHelper(user).get_courses()


def rename_courses_prompt() -> None:
    clear()

    print(f"""Do you wish to rename any of your courses?


    [0] No  [default]

    [1] Yes
    """)

    choice = bool_prompt("renamed_courses")

    if choice and not is_online:
        print("\nSince you are offline I am unable to retrieve the required information.\nPress enter to continue.\n")
        input()
        return

    if RequestHelper._instance is None:
        print("\n(Getting information about courses ...)\n")

    user = get_credentials()
    helper = RequestHelper(user)
    courses = helper._courses
    if not courses:
        print("No courses available ...   (cricket sounds)")
        input()
        return

    last_error = ""
    mapping: Dict[int, str] = config.renamed_courses or {}
    course_id_to_str = {course.course_id: course.name for course in courses}
    allowed = {course.course_id for course in courses}

    while True:
        print("Please provide a mapping between course ID's and their new names.\n")
        print("Available courses:\n")
        max_len = math.ceil(math.log(len(courses), 10))
        for course in courses:
            print(f"    [{course.course_id}]{' ' * (max_len - len(str(course.course_id)))}   {course.name}")

        print("""

Controls:
    input "q" to exit and save.
    input "d {ID}" to delete a mapping.
    input "{ID} {new_name}" to create a new mapping.

When encountering {ID} replace it with the course ID you want to make changes to.


For example:
    "26956 Hello world!" will rename the course with ID 26956 into "Hello World!"
    "d 26956" will delete the mapping of course number with ID 26956.

    "{3} abc" will *not* work.
    "26956 {def}" will rename the course to the literal "{def}" (with brackets).

""")
        print("Current mapping:\n")
        if mapping:
            print("{")
            sort = sorted(mapping.items(), key=lambda x: x[0])
            strs = [f"    {k} ({course_id_to_str[k]})" for k, _ in sort]
            max_len = max((len(st) for st in strs))

            for st, (_, v) in zip(strs, sort):
                print(f"{st.ljust(max_len)}  =>  {repr(v)}")
            print("}\n")
        else:
            print("{}\n")

        if last_error:
            print(f"{error_text} {last_error}\n")
            last_error = ""

        inp = input()
        if inp == "q":
            break

        clear()

        # TODO: Test this more
        if inp == "":
            print("Please provide anything.")

        parts = inp.split(" ")
        if len(parts) < 2:
            last_error = "Please separate your values with a space."
            continue

        if parts[0] == "d":
            if parts[1] == "":
                last_error = "Please provide a course number."

            try:
                num = int(parts[1])
            except ValueError as ex:
                last_error = "Parsing the number failed.\nReason: " + str(ex)
                continue

            if num not in mapping:
                last_error = f"The entered value ({repr(num)}) is not in the mapping."
                continue

            del mapping[num]

        else:
            try:
                num = int(parts[0])
            except ValueError as ex:
                last_error = "Parsing the number failed.\nReason: " + str(ex)
                continue

            if num not in allowed:
                last_error = f"The entered value ({repr(num)}) not in allowed course ID's."
                continue

            if parts[1] == "":
                last_error = "The course name is empty. To untrack a course put it into the blacklist."
                continue

            mapping[num] = " ".join(parts[1:])

    config.renamed_courses = mapping


def make_subdirs_prompt() -> None:
    clear()

    print(f"""Do you wish to create subdirectories in the Course folder?
    
If enabled, things like assignments get their own directory containing all files.
Otherwise the files are stored along with all others in the root directory of the course.

""")

    bool_prompt("make_subdirs")


def dont_download_videos_prompt() -> None:
    clear()
    print("""Do you want to download videos on this device?

This usually takes up a lot of space on your hard drive and may take
a long time to download if you have a slow internet connection.

""")

    bool_prompt("download_videos")


def follow_external_links_prompt() -> None:
    # Later: Check if this is useful
    clear()
    print("Do you want me to follow all external links mentioned in a course and also download those files?")

    bool_prompt("follow_links")


def isis_config_wizard() -> None:
    global was_in_configuration
    was_in_configuration = True

    rename_courses_prompt()
    whitelist_prompt()
    blacklist_prompt()
    dont_download_videos_prompt()
    follow_external_links_prompt()
    was_in_configuration = False

    print("Thank you for your time - everything is saved!\n")


def run_config_wizard() -> None:
    global was_in_configuration
    was_in_configuration = True

    authentication_prompt()
    filename_prompt()
    timer_prompt()

    throttler_prompt()
    update_policy_prompt()
    telemetry_data_prompt()
    was_in_configuration = False

    print("Thank you for your time - everything is saved!\n")


@on_kill(3)
def unexpected_exit_in_wizard() -> None:
    if was_in_configuration:
        print("\nThe configuration wizard was killed unexpectedly.\nI will continue with the default for all options which you have not configured.")


def main() -> None:
    acquire_file_lock_or_exit()
    if is_autorun:
        exit(1)

    print("""Hello there 👋

You can choose one of the following actions

    [v] view the current configuration
""")
    if not is_windows:
        print(f"    [e] export the current configuration to\n        `{export_config_file_location}`")

    print(f"\n\n    [{Style.BRIGHT}default{Style.RESET_ALL}] run the configuration wizard\n")

    choice = input()
    print()

    # if choice.lower() == "i":
    #     isis_config_wizard()
    #     return

    if choice.lower() == "v":
        print("\nThe configuration is the following:\n")
        print(yaml.dump(config.to_dict()))
        return

    if not is_windows and choice.lower() == "e":
        print("Exporting current configuration ...")
        with open(export_config_file_location, "w") as f:
            f.write(generate_current_config_str())
        return

    run_config_wizard()


if __name__ == "__main__":
    main()
