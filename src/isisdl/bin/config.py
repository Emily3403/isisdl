#!/usr/bin/env python3
from getpass import getpass
from typing import Union, Set, List, Tuple, Optional

from crontab import CronTab

from isisdl.backend.crypt import encryptor
from isisdl.share.settings import is_first_time, is_windows
from isisdl.share.utils import config_helper, get_input

explanation_depth = 2
indent = "    "


def generic_prompt(question: str, values: List[Tuple[str, str, str]], default: int, overwrite_output: Optional[str] = None) -> str:
    if overwrite_output:
        return overwrite_output

    print(question + "\n")
    for i, (val, tldr, detail) in enumerate(values):
        print(f"{indent}{i}. {val} {' [default]' if i == default else ''}")
        if explanation_depth > 0:
            if tldr:
                for item in tldr.split("\n"):
                    print(f"{indent * 2}{item}")

        if explanation_depth > 1:
            if detail:
                print()
                for item in detail.split("\n"):
                    print(f"{indent * 2}{item}")

        print()

    choice = get_input("", allowed={str(i) for i in range(len(values))} | {""})
    if choice == "":
        choice = str(default)

    return choice


def explanation_depth_prompt() -> None:
    if is_first_time:
        print("It seams as if this is your first time executing isisdl. Welcome <3\n")

    print("I will guide you through ~2min of configuration.\n")

    choice = generic_prompt("Which level of detail do you want?", [
        ("None", "Just accept the defaults and be done with it.", ""),
        ("TLDR", "A very brief summary of what is happening for every point", ""),
        ("Full details", "I will give you a full explanation of all the points and which choices to choose in certain scenarios.",
         "If you are reading this the first time it is recommended to use this option when first installing.")
    ],
                            2, overwrite_output="")

    global explanation_depth
    explanation_depth = int(choice)

    print()


def authentication_prompt() -> None:
    choice = generic_prompt("There are four ways of storing your password.", [
        ("Encrypted in the database", "You will have to enter your password every time.",
         "This is ideal for a multi-user system where someone knows of `isisdl` and would go ahead and read the database."),
        ("Clear text in the database", "No password required, but less security",
         "This is ideal for a private setup where you can be certain nobody will read your data.\nSince the database is hard "
         "to find and not just a text file it is pretty hard to programmatically analyze and extract passwords from it."),
        ("Manually entering the information every time", "Most secure, but also most annoying", "Use this when you want maximum security and are paranoid."),

    ], default=0, overwrite_output="")

    config_helper.set_user_store(choice)

    if choice in {"0", "1"}:
        print("Please provide authentication for ISIS.")
        username = input("Username (ISIS): ")
        password = getpass("Password (ISIS): ")
        if choice == "0":
            enc_password = getpass("Password (Encryption): ")
            password = encryptor(enc_password, password).decode()

        config_helper.set_user(username, password)

    else:
        print("Alright, no passwords will be stored.")

    print()


def filename_prompt() -> None:
    choice = generic_prompt(r"""For some applications the file name is important.
Some programming languages have restrictions / inconveniences when working with specific characters.
To combat this you may want to enable a specific file name scheme.

If you already have existing files they will be renamed automatically and transparently with the next startup of `isisdl`.""", [
        ("No replacing.", """All characters except "/" are left as they are.""", ""),
        ("Replace all non-url safe characters", """"#%&/:;<=>@\\^`|~-$" → "."\n"[]{}" → "()""""", """E.g. LaTeX needs escaping of "_" → "\\_"."""),

    ], default=0, overwrite_output="")

    config_helper.set_filename_scheme(choice)

    print()


def throttler_prompt() -> None:
    choice = generic_prompt("""If you wish you can throttle your download speed to a limit.
Do you want to do so?

You may overwrite this option by setting the `-d, --download-rate` flag.""", [
        ("Yes", "", ""),
        ("No", "", ""),

    ], default=1, overwrite_output="")

    amount = None
    if choice == "0":
        while True:
            try:
                amount = input("How many MiB/s am I allowed to consume? ")
                break
            except ValueError:
                print("\nI did not quite catch that")

    config_helper.set_throttle_rate(amount)

    print()


def cron_prompt() -> None:
    if is_windows:
        return

    choice = generic_prompt("""[Linux only]
Do you want me to schedule a Cron-Job to run `isisdl` every x hours?""", [
        ("No", "", ""),
        ("1 Hour", "", "Note: done with the `@hourly` target. Cron must support it."),
        ("24 Hours", "", "Note: done with the `@daily` target. Cron must support it."),

    ], default=0, overwrite_output="")

    with CronTab(user=True) as cron:

        command = next(cron.find_command("isisdl"), None)
        if command:
            print("It seams as if isisdl is already configured to run as a Cron-Job.")
            if choice == "0":
                second = get_input("Should I remove the entry? [y/n] ", {"y", "n"})
                if second == "y":
                    cron.remove(command)
            else:
                cron.remove(command)

        if choice in {"1", "2"}:
            import isisdl.__main__ as __main__
            job = cron.new(__main__.__file__, f"isisdl autogenerated", user=True)

            if choice == "1":
                job.setall("@hourly")
            else:
                job.setall("@daily")

    print()


def telemetry_data_prompt() -> None:
    choice = generic_prompt("""I would like to collect some data from you.
The data is primarily used to ensure `isisdl` is working correctly on all platforms and all courses.
It would be a *huge* benefit for developing if you share the extended data with me. But if you don't want to that is fine as well.

Also it is really useful to know for how many users I'm designing this library
and what requirements they have (runtime of `isisdl`, platform, etc.).

I've previously relied on assertions and users reporting these assertions on github.
This system is really inconvenient for both parties and there would be a lot of time saved when using this version.

You will find a detailed breakdown of what data is collected in the "Full details" option.
""", [
        ("No", "No data will be collected.", ""),
        ("Basic", "This covers all data which is used by `isisdl` itself.",
         "- Ping on run"
         "- Wrong blacklisting of urls"),
        ("Extended", "This covers all additional data e.g. about your system and configuration",
         f"- Your Platform\n"
         f"- Average connection speed\n"
         f"- Your config\n{indent}If multiple users have the same option disabled / enabled it might be useful to update the defaults accordingly."
         "- General metadata of your subscribed ISIS courses"
         f"\n{indent}- Number of courses"
         f"\n{indent}- Number of files"

         ),

    ], default=0, overwrite_output="")

    config_helper.set_telemetry(choice)


def main() -> None:
    config_helper.delete_config()

    explanation_depth_prompt()
    authentication_prompt()
    filename_prompt()
    throttler_prompt()
    cron_prompt()
    telemetry_data_prompt()

    # TODO:
    #   Global update enable / disable
    #   When executing as a script have a option to install from last working commit
    #   Nag the user to send at least a ping
    #   Last commit message
    #   H265

    print(config_helper.export_config())

    # Telemetry TODO:
    #   Detected wrong files across restarts


if __name__ == "__main__":
    main()
