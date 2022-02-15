#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Optional, Union

import requests
from packaging import version
from packaging.version import Version, LegacyVersion

from isisdl.backend.utils import config
from isisdl.version import __version__


def check_pypi_for_version() -> Optional[Union[LegacyVersion, Version]]:
    # Inspired from https://pypi.org/project/pypi-search
    to_search = requests.get("https://pypi.org/project/isisdl/").text
    found_version = re.search("<h1 class=\"package-header__name\">\n *(.*)?\n *</h1>", to_search)

    if found_version is None:
        return None

    groups = found_version.groups()
    if groups is None or len(groups) != 1:
        return None

    return version.parse(groups[0].split()[1])


def check_github_for_version() -> Optional[Union[LegacyVersion, Version]]:
    badge = requests.get("https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg").text
    if "passing" not in badge:
        return None

    res = requests.get("https://raw.githubusercontent.com/Emily3403/isisdl/main/src/isisdl/version.py")
    if not res.ok:
        return None

    found_version = re.match("__version__ = \"(.*)?\"", res.text)
    if found_version is None:
        return None

    return version.parse(found_version.group(1))


def install_latest_version() -> None:
    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()

    update_policy = config.update_policy
    if update_policy is None:
        return

    correct_version = version_github if update_policy.endswith("git") else version_pypi

    if correct_version is None:
        return

    if correct_version <= version.parse(__version__):
        return

    print(f"\nThere is a new version of isisdl available: {correct_version} (current: {__version__}).")

    if update_policy.startswith("notify"):
        return

    print("According to your update policy I will auto-install it.\n")
    if update_policy == "install_pip":
        ret = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "isisdl"])

    elif update_policy == "install_github":
        old_dir = os.getcwd()
        with TemporaryDirectory() as tmp:
            os.chdir(tmp)
            print(f"Cloning the repository into {tmp} ...")
            ret = subprocess.call(["git", "clone", "https://github.com/Emily3403/isisdl"])
            if ret:
                print(f"Cloning failed with exit code {ret}")
                return

            print("Installing with pip ...")
            ret = subprocess.call([sys.executable, "-m", "pip", "install", "./isisdl"])
            os.chdir(old_dir)

    else:
        assert False

    if ret == 0:
        print("Successfully updated!")
        exit(0)
    else:
        print("Updating failed… why?")
        exit(ret)
