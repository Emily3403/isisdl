#!/usr/bin/env python3
import os
import time
from argparse import ArgumentParser, RawTextHelpFormatter
from collections import defaultdict
from hashlib import sha256
from typing import Dict, List

from isisdl.share.settings import working_dir_location, blacklist_test_checksums_file_name_location

from isisdl.backend.api import Course
from isisdl.backend.checksums import CheckSumHandler
from isisdl.share.utils import logger, path


def get_args():
    parser = ArgumentParser(prog="isisdl", formatter_class=RawTextHelpFormatter, description="""
    This program checks for checksum collisions in a directory.""")

    parser.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    parser.add_argument("-v", "--verbose", help="Enable debug output", action="store_true")

    parser.add_argument("-d", "--dir", help="Set the directory to be checked", type=str, default=working_dir_location)
    parser.add_argument("-e", "--exclude", help="Set a list of paths to be excluded", type=str, nargs="*", default=[])

    the_args, unknown = parser.parse_known_args()

    with open(path(blacklist_test_checksums_file_name_location)) as f:
        the_args.exclude.extend(item for item in f.read().splitlines() if item.strip())

    return the_args


args = get_args()


def time_it(func):
    s = time.perf_counter()
    list(func())
    print(f"Took {time.perf_counter() - s:.3f}s")


def calc_checksum(file: str, csh):
    try:
        with open(file, "rb") as f:
            return csh.calculate_checksum(f)

    except OSError:
        logger.warning(f"I could not open the file {file}. Ignoring this file.")


def main():
    def print_percent(num: int, max_num: int):
        return f"{num} / {max_num} = {num / (max_num or 1) * 100}%"

    logger.info("Starting to build a file list")
    all_files = [os.path.join(p, f) for p, _, filenames in os.walk(args.dir, followlinks=True) for f in filenames if not any(item in os.path.join(p, f) for item in args.exclude)]
    logger.info(f"Analyzing {len(all_files)} files")

    csh = CheckSumHandler(Course("_", "0"), autoload_checksums=False)

    res = [calc_checksum(file, csh) for file in all_files]

    checksum_mapping = {file: checksum for file, checksum in zip(all_files, res) if checksum is not None}
    logger.info(f"I could calculate a hash for {len(checksum_mapping)} files.")

    checksums: Dict[str, int] = {}
    for key, value in checksum_mapping.items():
        checksums.setdefault(value, 0)
        checksums[value] += 1

    rev_checksums: Dict[str, List[str]] = {}
    for key, value in checksum_mapping.items():
        rev_checksums.setdefault(value, list()).append(key)

    same_checksums = {k: v for k, v in rev_checksums.items() if len(v) > 1 and any(os.path.basename(v[0]) != os.path.basename(item) for item in v)}

    def sha256sum(filename):
        sha = sha256()
        with open(filename, 'rb', buffering=0) as f:
            while True:
                data = f.read(1024 * 64)
                if not data:
                    break
                sha.update(data)

        return sha.hexdigest()

    different_files = 0
    for key_, value_ in same_checksums.items():
        # Now test if the files are actually equal

        chs = {file: sha256sum(file) for file in value_}

        sha_sums = {item for item in chs.values()}
        if len(sha_sums) > 1:
            different_files += len(sha_sums)

        m_len = max(map(len, chs))

        chs_rev = defaultdict(list)
        for key, value in chs.items():
            chs_rev[value].append(key)

        if not all(item == sha256sum(value_[0]) for item in chs.values()):
            logger.info(f"Different files (Checksum: {key_})\n" + "\n".join(f"{file.ljust(m_len)}  {sha = }" for file, sha in chs.items()) + "\n")

        else:
            logger.debug("Duplicate files:\n" + "\n".join(f"{file.ljust(m_len)}  {sha}" for file, sha in chs.items()) + "\n")

        # logger.debug(
        #     f"The following have the checksum {key_}:\n\n" + f"{'Are equal' if all(item == sha256sum(value_[0]) for item in chs.values()) else 'Not equal'}\n\n" + "\n".join(value_) + "\n\n"
        #     + "\n".join() + "\n")

    logger.info(f"Number of files with the same checksum:       {print_percent(sum(item for item in checksums.values() if item > 1), len(checksum_mapping))}")
    logger.info(f"Number of files that were actually different: {print_percent(different_files, len(checksum_mapping))}")


if __name__ == '__main__':
    main()
