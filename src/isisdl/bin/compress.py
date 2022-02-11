#!/usr/bin/env python3
import os
import shutil
import subprocess
import time
import datetime
from pathlib import Path
from threading import Thread
from typing import Optional

from downloads import MediaType
from isisdl.backend.crypt import get_credentials
from isisdl.settings import is_windows, has_ffmpeg, status_time
from request_helper import RequestHelper
from utils import error_text, is_h265, on_kill, HumanBytes, do_ffprobe


def check_ffmpeg_exists() -> None:
    if has_ffmpeg:
        return

    print(error_text)
    if is_windows:
        print(
            "I could not find the executable `ffmpeg`.\nYou probably haven't installed it.\nPlease follow the steps at https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/ to install it.")

    else:
        print("I could not find the executable `ffmpeg` in your PATH.\nTo use the compress functionality install it with your favorite package manager.")

    exit(1)


stop_encoding: Optional[bool] = None
total_prev_size = 0
total_after_size = 0
curr_file: Optional[Path] = None


@on_kill(5)  # type: ignore
def run_ffmpeg_till_finished() -> None:
    global stop_encoding
    if stop_encoding is None:
        return

    stop_encoding = True

    print("\n\nPlease wait for the conversion to be finished!")
    probe = do_ffprobe(str(curr_file))
    video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
    if video_stream is not None and "duration" in video_stream:
        print(f"(Duration: {datetime.timedelta(seconds=int(float(video_stream['duration'])))}:00)\n")
    else:
        print()

    while True:
        if stop_encoding is False:
            break
        time.sleep(status_time)

    print(f"Total previous size: {HumanBytes.format_str(total_prev_size)}")
    print(f"After conversion:    {HumanBytes.format_str(total_after_size)}")


def convert() -> None:
    global stop_encoding
    global total_prev_size
    global total_after_size
    global curr_file

    check_ffmpeg_exists()
    helper = RequestHelper(get_credentials())

    stop_encoding = False

    for course in helper.courses:
        videos = list(Path(course.path(MediaType.video.dir_name)).glob("*"))
        for video in videos:
            if stop_encoding:
                stop_encoding = False
                return

            if is_h265(str(video)):
                continue

            curr_file = video

            subprocess.Popen([
                "ffmpeg",
                "-i", str(video),
                "-crf", "35",
                "-c:v", "libx265",
                "-c:a", "copy",
                "-preset", "fast",
                video.parent.joinpath(".tmp_" + video.name)
            ], stdin=subprocess.DEVNULL, preexec_fn=lambda: os.setpgrp() if is_windows else lambda: None).wait()  # type: ignore

            total_prev_size += video.stat().st_size
            shutil.move(str(video.parent.joinpath(".tmp_" + video.name)), str(video))
            total_after_size += video.stat().st_size

    return


def main() -> None:
    print("Attention: If you rename a compressed file and the database is deleted you will lose this file.\nThe only way to recover it is by renaming it back to its original name.")
    # Run the conversion in a separate thread so if killed it will still run
    runner = Thread(target=convert)
    runner.start()
    runner.join()


if __name__ == '__main__':
    main()
