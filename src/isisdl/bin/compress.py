#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from typing import Optional, List, Dict, Any

from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import print_log_messages
from isisdl.backend.request_helper import RequestHelper, pre_status, PreMediaContainer
from isisdl.backend.utils import error_text, is_h265, on_kill, HumanBytes, do_ffprobe, acquire_file_lock_or_exit, generate_error_message
from isisdl.settings import is_windows, has_ffmpeg, status_time, ffmpeg_args, enable_multithread


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


def vstream_from_probe(probe: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if probe is None:
        return None

    return next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)


def format_seconds(seconds: float) -> str:
    # Copied from https://stackoverflow.com/a/1384506
    # datetime.timedelta formats the time as h:mm:ss instead of hh:mm:ss. So I can't use that…
    hours = seconds // (60 * 60)
    seconds %= (60 * 60)
    minutes = seconds // 60
    seconds %= 60
    return "%02i:%02i:%02i" % (hours, minutes, seconds)


def make_temp_filename(file: PreMediaContainer) -> str:
    head, tail = os.path.split(file.path)
    return os.path.join(head, ".tmp_" + tail)


stop_encoding: Optional[bool] = None


@on_kill(5)
def run_ffmpeg_till_finished() -> None:
    global stop_encoding

    if compress_status is None:
        return

    if stop_encoding is None:
        return

    stop_encoding = True

    compress_status.shutdown()

    while True:
        if stop_encoding is False:
            break
        time.sleep(status_time)

    compress_status._running = False
    compress_status.generate_final_message()


def calculate_efficiency(now: float, prev: float) -> int:
    if -0.1 <= prev <= 0.1:
        return 0

    return int((now - prev) / prev * 100)


def calculate_average(lst: List[int]) -> float:
    if not lst:
        return 0
    return sum(lst) / len(lst)


class CompressStatus(Thread):
    cur_file: Optional[PreMediaContainer]
    cur_file_probe: Optional[Dict[str, Any]]
    ffmpeg: Optional[subprocess.Popen[str]]

    def __init__(self, files: List[PreMediaContainer], helper: RequestHelper) -> None:
        self.files = files
        self.helper = helper
        self.cur_file = None
        self.cur_file_probe = None
        self.ffmpeg = None
        self._running = True
        self._shutdown = False
        self.last_text_len = 0
        self.i = 0
        self.last_5_files_prev_size: List[int] = []
        self.last_5_files_cur_size: List[int] = []

        self.session_total_prev_size = 0
        self.session_total_cur_size = 0
        self.session_files_done = 0

        self.total_files_available = len([item for item in files if item.size == os.stat(item.path).st_size])
        self.total_prev_size = 0
        self.total_now_size = 0
        self.total_prev_size_of_compressed = 0
        self.total_cur_size_of_compressed = 0
        self.total_files_done = 0

        for file in files:
            self.total_prev_size += file.size

            actual_file_size = os.stat(file.path).st_size
            self.total_now_size += actual_file_size

            if actual_file_size != file.size:
                self.total_prev_size_of_compressed += file.size
                self.total_cur_size_of_compressed += actual_file_size
                self.total_files_done += 1

        super().__init__(daemon=True)

    def done_thing(self, file: PreMediaContainer) -> None:
        new_file_size = os.stat(file.path).st_size

        self.total_now_size -= file.size
        self.total_now_size += new_file_size

        self.session_total_prev_size += file.size
        self.session_total_cur_size += new_file_size

        self.total_prev_size_of_compressed += file.size
        self.total_cur_size_of_compressed += new_file_size

        self.session_files_done += 1
        self.total_files_done += 1

        if len(self.last_5_files_cur_size) > 5:
            self.last_5_files_cur_size.pop(0)
        if len(self.last_5_files_prev_size) > 5:
            self.last_5_files_prev_size.pop(0)

        self.last_5_files_cur_size.append(new_file_size)
        self.last_5_files_prev_size.append(file.size)

        # Reset old values
        self.cur_file = None
        self.cur_file_probe = None
        self.ffmpeg = None

    def start_thing(self, file: PreMediaContainer, ffmpeg: subprocess.Popen[str]) -> None:
        self.cur_file = file
        self.cur_file_probe = do_ffprobe(file.path)
        self.ffmpeg = ffmpeg

    def shutdown(self) -> None:
        self._shutdown = True

    def run(self) -> None:
        try:
            while self._running:
                time.sleep(status_time)

                log_strings = [
                    "",
                    f"Compressing videos {self.total_files_done} / {self.total_files_available} " + "." * self.i,
                    "",
                    "Total size before compression:     " + HumanBytes.format_pad(self.total_prev_size),
                    "Total size after  compression:     " + HumanBytes.format_pad(self.total_now_size),
                    "",
                    "Previous size of compressed files: " + HumanBytes.format_pad(self.total_prev_size_of_compressed),
                    "Current  size of compressed files: " + HumanBytes.format_pad(self.total_cur_size_of_compressed),
                    "Global efficiency: " + str(calculate_efficiency(self.total_cur_size_of_compressed, self.total_prev_size_of_compressed)) + "%",
                    "",
                    "",
                    f"Total files compressed this session:    {self.session_files_done}",
                    f"Total file size saved for this session: {HumanBytes.format_str(self.session_total_prev_size - self.session_total_cur_size)}",
                    "Efficiency for the last 5 files:        " +
                    str(calculate_efficiency(calculate_average(self.last_5_files_cur_size), calculate_average(self.last_5_files_prev_size))) + "%",
                    "", "",
                    "Currently processing:",
                    f"{self.cur_file.path}" if self.cur_file is not None else '',
                ]

                if self.ffmpeg is not None and self.ffmpeg.stderr is not None and self.cur_file_probe is not None:
                    ffmpeg_out = self.ffmpeg.stderr.readline()
                    if ffmpeg_out:
                        _elapsed_time = re.findall(r"time=(\d\d:\d\d:\d\d.\d\d) ", ffmpeg_out)
                        if _elapsed_time:
                            elapsed_time: Optional[str] = _elapsed_time[0]
                        else:
                            elapsed_time = None

                        _frame = re.findall(r"frame= *(\d+)", ffmpeg_out)
                        if _frame:
                            frame: Optional[int] = int(_frame[0])
                        else:
                            frame = None

                        _fps = re.findall(r"fps=(.+?) ", ffmpeg_out)
                        if _fps:
                            fps: Optional[float] = float(_fps[0])
                        else:
                            fps = None

                        video_stream = vstream_from_probe(self.cur_file_probe)
                        if elapsed_time is not None and frame is not None and fps is not None and self.cur_file is not None and self.cur_file_probe is not None and \
                                video_stream is not None and 'nb_frames' in video_stream and 'duration' in video_stream:
                            total_frames = int(video_stream['nb_frames'])
                            prev_size = os.stat(self.cur_file.path).st_size
                            if os.path.exists(make_temp_filename(self.cur_file)):
                                current_size = os.stat(make_temp_filename(self.cur_file)).st_size
                            else:
                                current_size = prev_size

                            estimated_file_size = current_size / max(frame, 1) * total_frames

                            log_strings.append("")
                            log_strings.append(f"File size:           {HumanBytes.format_pad(prev_size)}")
                            log_strings.append(f"Current size:        {HumanBytes.format_pad(current_size)}")
                            log_strings.append(f"Estimated file size: {HumanBytes.format_pad(estimated_file_size)}")
                            log_strings.append(f"Estimated efficiency: {calculate_efficiency(estimated_file_size, float(prev_size))}%")
                            log_strings.append("")
                            log_strings.append(f"Duration:     {format_seconds(float(video_stream['duration']))}")
                            log_strings.append(f"Current time: {elapsed_time[:-3]}")
                            log_strings.append(f"Percent done: {max(frame, 1) / total_frames * 100:.2f}%")
                            log_strings.append("")
                            log_strings.append(f"ETA: {format_seconds((total_frames - frame) / fps) if fps > 0.3 else '∞'}")

                if self._shutdown:
                    log_strings.extend(["", "Please wait for the compression to finish ..."])
                    if not is_windows:
                        log_strings.extend(["", "(If you kill me again, ffmpeg will continue to run in the background)", "To kill it execute `pkill -9 ffmpeg`"])

                if self._running:
                    self.last_text_len = print_log_messages(log_strings, self.last_text_len)

                self.i = (self.i + 1) % 4

        except Exception:
            generate_error_message()

    def generate_final_message(self) -> None:
        sizes = {course.name: (
            sum(item.size for item in self.files if item.course_id == course.course_id if item.size != os.stat(item.path).st_size),
            sum(os.stat(item.path).st_size for item in self.files if item.course_id == course.course_id if item.size != os.stat(item.path).st_size),
            sum(1 for item in self.files if item.course_id == course.course_id if item.size != os.stat(item.path).st_size),
        ) for course in self.helper.courses if sum(item.size for item in self.files if item.course_id == course.course_id if item.size != os.stat(item.path).st_size)}

        max_course_name_len = max(len(str(course)) for course in sizes)
        max_file_len = max(len(str(num_files)) for *_, num_files in sizes.values())
        log_strings = ["", "", "Summary of course size savings:", ""]
        for course, (prev_size, cur_size, num_files) in sizes.items():
            log_strings.append(f"{str(course).ljust(max_course_name_len)} ({str(num_files).rjust(max_file_len)} file{'s' if num_files > 1 else ' '}) "
                               f"{HumanBytes.format_pad(prev_size)} → {HumanBytes.format_pad(cur_size)}  ({calculate_efficiency(cur_size, prev_size)}%)")

        print_log_messages(log_strings, 0)


def compress(files: List[PreMediaContainer]) -> None:
    assert compress_status is not None
    try:
        global stop_encoding
        check_ffmpeg_exists()

        stop_encoding = False

        if sys.platform == "win32":
            def func_to_call() -> None:
                pass
        else:
            def func_to_call() -> None:
                os.setpgrp()

        for file in files:
            if stop_encoding:
                stop_encoding = False
                return

            new_file_name = make_temp_filename(file)

            if not file.path:
                continue

            probe = is_h265(file.path)
            if probe is None or probe is True:
                continue

            ffmpeg = subprocess.Popen([
                "ffmpeg",
                "-i", file.path,
                "-y", "-loglevel", "warning", "-stats",
                *ffmpeg_args,
                "-x265-params", "log-level=0",
                new_file_name
            ], stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=func_to_call, universal_newlines=True)

            compress_status.start_thing(file, ffmpeg)

            ffmpeg.wait()
            os.rename(new_file_name, file.path)

            compress_status.done_thing(file)

    except Exception:
        generate_error_message()


# TODO:
#   Remote compression?
#   Set nice score

def main() -> None:
    global compress_status
    acquire_file_lock_or_exit()
    print("Attention: If you rename a compressed file and the database is deleted you will lose this file.\nThe only way to recover it is by renaming it back to its original name.")
    print("\nPress enter to continue")
    input()

    user = get_credentials()
    pre_status.start()
    helper = RequestHelper(user)
    _content = list(filter(lambda x: x.is_video and os.path.exists(x.path), helper.download_content()))
    pre_status.stop()

    if enable_multithread:
        with ThreadPoolExecutor(os.cpu_count()) as ex:
            _ffprobes = list(ex.map(lambda x: vstream_from_probe(do_ffprobe(x.path)), _content))
    else:
        _ffprobes = [vstream_from_probe(do_ffprobe(item.path)) for item in _content]

    ffprobes = [item for item in _ffprobes if item is not None]
    no_bitrate = []
    content_and_ffprobe = []
    for con, ff in zip(_content, ffprobes):
        if "bit_rate" not in ff:
            no_bitrate.append(con)
        else:
            content_and_ffprobe.append((con, ff))

    # Sort by bitrate
    content = [item for item, _ in sorted(content_and_ffprobe, key=lambda pair: int(pair[1]["bit_rate"]), reverse=True)]
    content.extend(no_bitrate)

    compress_status = CompressStatus(content, helper)
    compress_status.start()

    # Run the conversion in a separate thread so, if killed, it will still run
    runner = Thread(target=compress, args=(content,))
    runner.start()
    runner.join()


compress_status: Optional[CompressStatus] = None

if __name__ == '__main__':
    main()
