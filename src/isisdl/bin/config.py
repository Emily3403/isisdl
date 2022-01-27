#!/usr/bin/env python3
import os
import subprocess
import sys
from getpass import getpass
from typing import List, Optional, Union, Set, Dict

from isisdl.backend.crypt import get_credentials, store_user
from isisdl.backend.downloads import SessionWithKey
from isisdl.backend.utils import get_input, User, clear, config, get_default_config, acquire_file_lock, database_helper, error_text
from isisdl.settings import is_windows, is_autorun, timer_file_location, service_file_location


def stored_prompt(prev: Optional[Union[str, bool, None]], allowed: Set[str]) -> None:
    if prev is None:
        return

    print(f"\n    [s] Use the stored option ", end="")
    allowed.add("s")

    if isinstance(prev, bool):
        print(("No", "Yes")[prev], end=".\n\n")  # Idk if I like this syntax :D
    else:
        print(f"`{prev}`.\n")


def bool_prompt(prev: Optional[Union[str, bool, None]], default: Optional[bool]) -> Optional[bool]:
    # Will return None iff [s] is selected.
    allowed = {"0", "1"}
    if default is not None:
        allowed.add("")

    stored_prompt(prev, allowed)

    choice = get_input(allowed)
    if choice == "":
        return default

    if choice == "s":
        return None

    return bool(int(choice))


def authentication_prompt() -> None:
    clear()
    print("""Do you wish to store your password?

    [0] No
    
    [1] Yes  [default]
""")

    # https://stackoverflow.com/a/47007761
    choice = bool_prompt(user_config["password"] and User.sanitize_name(str(user_config["username"])), True)

    if choice is None:
        return

    if choice is False:
        config["username"] = None
        config["password"] = None
        config["password_encrypted"] = None
        return

    while True:
        print("Please provide your authentication for ISIS.")
        username = input("Username: ")
        password = getpass("Password: ")

        print("\nChecking if the password works ...")
        worked = SessionWithKey.from_scratch(User(username, password))
        if worked is not None:
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

    store_user(User(username, password), additional_passphrase)


def filename_prompt() -> None:
    if is_windows:
        forbidden_chars = "<>:\"/\\|?*"
    else:
        forbidden_chars = "/"

    clear()
    print(f"""Some programs / programming languages have restrictions or 
inconveniences when it comes to working with special characters.

To combat this you can enable a safe-mode for the file names.
If enabled, only ASCII letters + digits + "." are permitted as filenames.

In order to maintain the readability of filenames,
the next character after a whitespace is capitalized.

If enabled a the filename would get renamed like this:
 "I am / a wierd 🐧 [filename]" → "IAmAWierdFilename"


--- Note ---
The character{'s' if is_windows else ''} `{forbidden_chars}` {'are' if is_windows else 'is'} always replaced (not supported on a filesystem level).
When changing this option every file will be re-downloaded.
------------


    [0] No  [default]
        
    [1] Yes
""")
    assert isinstance(default_config["filename_replacing"], bool)
    choice = bool_prompt(user_config["filename_replacing"], default_config["filename_replacing"])

    if choice is None:
        return

    config["filename_scheme"] = choice


def throttler_prompt() -> None:
    clear()
    print(f"""If you wish you can throttle your download speed to a limit.
Do you want to do so?

--- Note ---
You may overwrite this option by setting the `-d, --download-rate` flag.
------------


    [0] No  [default]
    
    [1] Only impose a limit for when `isisdl` automatically runs
    
    [2] Yes
""")
    allowed = {"0", "1", "2", ""}


    if user_config["throttle_rate"] and user_config["throttle_rate_autorun"]:
        print(f"\n    [s] Use the stored option {user_config['throttle_rate']} MiB/s (systemwide), {user_config['throttle_rate_autorun']} MiB/s (autorun).\n")

    elif user_config["throttle_rate"]:
        print(f"\n    [s] Use the stored option {user_config['throttle_rate']} MiB/s (systemwide).\n")
        allowed.add("s")

    elif user_config["throttle_rate_autorun"]:
        print(f"\n    [s] Use the stored option {user_config['throttle_rate_autorun']} MiB/s (autorun).\n")
        allowed.add("s")

    choice = get_input(allowed)

    if choice == "s":
        return

    if choice == "" or choice == "0":
        config["throttle_rate"] = None
        config["throttle_rate_autorun"] = None
        return

    if choice == "1":
        config_str = "throttle_rate_autorun"
    else:
        config_str = "throttle_rate"

    while True:
        print()
        try:
            amount = str(int(input("How many MiB/s am I allowed to consume? ")))
            config[config_str] = amount
            return
        except ValueError as ex:
            print(f"\nI did not quite catch that:\n{ex}\n")


def timer_prompt() -> None:
    if is_windows:
        return

    def run_cmd_with_error(args: List[str]) -> None:
        result = subprocess.run(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        if result.returncode:
            print(error_text)
            print(f"The command `{' '.join(result.args)}` exited with exit code {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}")
            print("\nPress [enter] to continue")
            input()

    clear()
    print("[Linux only]\n\nDo you want me to install a systemd timer to run `isisdl` every hour?\n")

    not_systemd = subprocess.check_call(["systemctl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    if not_systemd:
        print(f"""{error_text}
It seams as if you are not running systemd.
Since this feature is systemd specific, I can't install it on your system.
If you think this is a bug please submit an error report at 
https://github.com/Emily3403/isisdl/issues

Press [enter] to continue.""")
        input()
        return

    print("If you enable this option the files will automagically appear in\n`isisdl_downloads` and you will never have to execute `isisdl` again.")

    if user_config["password_encrypted"]:
        print(f"""\n{error_text}
I cannot run `isisdl` automatically if the password is encrypted.
Do you wish to store the password unencrypted?

    [0] No
    
    [1] Yes
""")
        choice = bool_prompt(None, None)

        if choice is False:
            return

        user = get_credentials()
        store_user(user)
        print("\nThe password is now stored unencrypted.\n")
        print("Do you wish to enable the timer?")

    print(f"""
--- Note ---
The configuration file is located at 
`{timer_file_location}`
if you want to tune the time manually
------------


    [0] No
    
    [1] Yes  [default]
""")

    choice = bool_prompt(os.path.exists(timer_file_location), True)

    if choice is None:
        return

    if choice is False:
        if not os.path.exists(timer_file_location):
            return

        run_cmd_with_error(["systemctl", "--user", "disable", "--now", "isisdl.timer"])
        run_cmd_with_error(["systemctl", "--user", "daemon-reload"])

        if os.path.exists(timer_file_location):
            os.remove(timer_file_location)

        if os.path.exists(service_file_location):
            os.remove(service_file_location)

        return

    import isisdl.bin.autorun
    with open(service_file_location, "w") as f:
        f.write(f"""# isisdl autorun service
# This file was autogenerated by the `isisdl-config` utility.

[Unit]
Description=isisdl
Wants=isisdl.timer

[Service]
Type=oneshot
ExecStart={sys.executable} {isisdl.bin.autorun.__file__}

[Install]
WantedBy=multi-user.target
""")

    with open(timer_file_location, "w") as f:
        f.write(f"""# isisdl autorun timer
# This file was autogenerated by the `isisdl-config` utility.

[Unit]
Description=isisdl
Wants=isisdl.service

[Timer]
Unit=isisdl.service
OnCalendar=hourly

[Install]
WantedBy=timers.target
""")

    run_cmd_with_error(["systemctl", "--user", "enable", "--now", "isisdl.timer"])
    run_cmd_with_error(["systemctl", "--user", "daemon-reload"])


def telemetry_data_prompt() -> None:
    clear()
    print("""In order to ensure that all courses are downloaded correctly I would like to
collect some metadata from your courses, setup and configuration of isisdl.

I've previously relied on assertions and users reporting these assertions on github.
This system is really inconvenient for both parties and wastes a lot of time.

If you allow it, the program `isisdl` will automatically contact a server when it can report something.

I collect the following:
  - Wrong blacklisting of urls
  - If files are missing upon rediscovery
  - If two files have the same size (or for videos the same length)
  - Your platform
  - Your configuration
  
  
    [0] No
    
    [1] Yes  [default]
""")
    assert isinstance(default_config["telemetry_policy"], bool)
    choice = bool_prompt(user_config["telemetry_policy"], default_config["telemetry_policy"])

    config["telemetry_policy"] = choice


def update_policy_prompt() -> None:
    clear()
    print("""Do you want me to auto-install updates when available?
    
The version on github is by design always more recent than the one on pip. 
It should have no stability issues since the update is only installed if they pass the tests.

The version on pip should be always working.
It is usually pushed a few days after github release.


    [0] No
    
    [1] Notify me when updates are available on pip
    
    [2] Notify me when updates are available on github
    
    [3] Install from pip  [default]
    
    [4] Install from github
""")

    allowed = {"", "0", "1", "2", "3", "4"}

    stored_prompt(user_config["update_policy"], allowed)
    choice: Optional[str] = get_input(allowed)

    if choice == "s":
        return

    elif choice == "0":
        choice = None
    elif choice == "1":
        choice = "notify_pip"
    elif choice == "2":
        choice = "notify_github"
    elif choice == "3" or choice == "":
        choice = "install_pip"
    else:
        choice = "install_github"

    config["update_policy"] = choice


# TODO: Default values
#   Cron and no store of passwords?


def main() -> None:
    acquire_file_lock()
    if is_autorun:
        exit(1)

    print(f"""I will guide you through a short configuration phase of about 4min.
It is recommended that you read the options carefully.
""")

    is_first_time = True
    if is_first_time:
        print("If you wish to re-configure me run `isisdl-config`.\n\nPlease press enter to continue.\n")

    else:
        print("""You can
    [d] {'accept' if is_first_time else 'reset to'} the defaults
    [e] export the current configuration

If you want to {'accept' if is_first_time else 'reset to'} the default press [d] and [enter].""")

    choice = input("")
    if choice.lower() == "d":
        print(f"\n{'Accepted' if is_first_time else 'Reset to'} the defaults!")
        return


    authentication_prompt()
    update_policy_prompt()
    timer_prompt()
    filename_prompt()
    throttler_prompt()

    telemetry_data_prompt()

    print("Thank you for your time - everything is saved!\n")


default_config = get_default_config()

user_config: Dict[str, Union[bool, str, None]] = {k: None for k in default_config}
user_config.update(database_helper.get_config())


if __name__ == "__main__":
    main()
