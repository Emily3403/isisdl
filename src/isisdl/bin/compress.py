#!/usr/bin/env python3
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, cast, Any

import resource

from downloads import MediaType
from isisdl.backend.crypt import get_credentials
from isisdl.settings import is_windows
from request_helper import RequestHelper
from utils import error_text, do_ffprobe, is_h265


def check_ffmpeg_exists() -> None:
    if shutil.which("ffmpeg") is not None:
        return

    print(error_text)
    if is_windows:
        print(
            "I could not find the executable `ffmpeg`.\nYou probably haven't installed it.\nPlease follow the steps at https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/ to install it.")

    else:
        print("I could not find the executable `ffmpeg` in your PATH.\nTo use the compress functionality install it with your favorite package manager.")

    exit(1)


def main() -> None:
    check_ffmpeg_exists()
    helper = RequestHelper(get_credentials())

    for course in helper.courses:
        for video in Path(course.path(MediaType.video.dir_name)).glob("*"):
            if is_h265(str(video)):
                continue

            subprocess.call([
                "ffmpeg",
                "-i", str(video),
                "-crf", "35",
                "-c:v", "libx265",
                "-c:a", "copy",
                "-preset", "fast",
                video.parent.joinpath(".tmp_" + video.name)
            ])

            shutil.move(str(video.parent.joinpath(".tmp_" + video.name)), str(video))

            exit(1)
            print()
            pass

    return


# TODO:
#   Limit cpu
#   integrate into config
#

if __name__ == '__main__':
    main()
