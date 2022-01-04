#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

import requests
from bs4 import BeautifulSoup

from isisdl.share.utils import logger, get_input, config_helper
from isisdl.version import __version__


def check_pypi_for_version() -> str:
    # Inspired from https://pypi.org/project/pypi-search

    soup = BeautifulSoup(requests.get("https://pypi.org/project/isisdl/").text, 'html.parser')
    package_name_header = soup.find('h1', class_='package-header__name')
    version = package_name_header.text.split()[1]

    return str(version)


def check_github_for_version() -> str:
    res = requests.get("https://raw.githubusercontent.com/Emily3403/isisdl/main/src/isisdl/version.py")
    if not res.ok:
        logger.error("I could not obtain the latest version. Probably the link, which is hard-coded, is wrong.")
        assert False

    version = re.match("__version__ = \"(.*)?\"", res.text)
    if version is None:
        logger.error("I could not parse the specified version.")
        assert False

    return version.group(1)


def main() -> None:
    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()

    last_ignored_version = config_helper.get_last_ignored_version()

    if last_ignored_version == version_github:
        return

    if version_github > __version__:
        print(f"\nThere is a new version available: {version_github} (current: {__version__}).")
        if version_pypi == version_github:
            print("You're in luck: The new version is already available on PyPI.\n")
        else:
            print("Unfortunately the new version is not uploaded to PyPI yet.\n")

        possible_choices = {"i", "g", "s"}
        message = """Do you want to:
    [i] ignore this update
    [g] install the new version from github
    [s] show me the commands - I'll handle it myself"""

        if version_pypi == version_github:
            message += "    [p] install the new version from PyPI"
            possible_choices.add("p")

        message += "\n"
        print(message)

        choice = get_input("", possible_choices)
        if choice == "s":
            print("To install isisdl from github type the following into your favorite shell!")
            print("cd /tmp")
            print("git clone https://github.com/Emily3403/isisdl")
            print("pip install ./isisdl")
            return

        if choice == "i":
            config_helper.set_last_ignored_version(version_github)
            return

        if choice == "g":
            old_dir = os.getcwd()
            with TemporaryDirectory() as tmp:
                os.chdir(tmp)
                print(f"Cloning the repository into {tmp} ...")
                ret = subprocess.check_call(["git", "clone", "https://github.com/Emily3403/isisdl"])
                if ret:
                    print(f"Cloning failed with exit code {ret}")
                    return

                print("Installing with pip ...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "./isisdl"])
                os.chdir(old_dir)
                return

        if choice == "p":
            subprocess.check_call([sys.executable, "-m", "pip", "install", "isisdl"])
            return

    pass


if __name__ == '__main__':
    main()
