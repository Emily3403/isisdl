#!/usr/bin/env python3
import os
from typing import List

from isisdl.share.settings import course_dir_location
from isisdl.share.utils import path, sanitize_name, logger


def main() -> None:
    all_files: List[str] = []

    # Copied from https://stackoverflow.com/a/13454267
    for root, dirs, files in os.walk(path(course_dir_location)):
        # Skip hidden files
        all_files.extend(os.path.join(root, f) for f in files if not f[0] == '.')
        dirs[:] = [d for d in dirs if not d[0] == '.']

    logger.info(f"Found {len(all_files)} files.")

    num_rename = 0
    for file in all_files:
        root, name = os.path.split(file)
        new_name = sanitize_name(name)
        if name != new_name:
            os.rename(os.path.join(root, name), os.path.join(root, new_name))
            num_rename += 1

    logger.info(f"Successfully renamed {num_rename} files.")


if __name__ == '__main__':
    main()
