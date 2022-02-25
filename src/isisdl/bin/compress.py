#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from statistics import variance, stdev, mean
from threading import Thread, Lock
from typing import Optional, List, Dict, Any, Tuple

import numpy as np

from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import print_log_messages
from isisdl.backend.request_helper import RequestHelper, pre_status, PreMediaContainer
from isisdl.backend.utils import error_text, is_h265, on_kill, HumanBytes, do_ffprobe, acquire_file_lock_or_exit, generate_error_message, OnKill, database_helper
from isisdl.settings import is_windows, has_ffmpeg, status_time, ffmpeg_args, enable_multithread, compress_duration_for_to_low_efficiency, compress_std_mavg_size, \
    compress_minimum_stdev, compress_minimum_score, compress_score_mavg_size, compress_insta_kill_score, compress_duration_for_insta_kill, is_first_time


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


def metadata_hash_from_file(file: str) -> Optional[str]:
    prev_metadata = vstream_from_probe(do_ffprobe(file))

    if prev_metadata is None:
        return None

    return prev_metadata["extradata_hash"]


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
current_pid: Optional[int] = None
total_time_for_compression = 0


@on_kill(5)
def run_ffmpeg_till_finished() -> None:
    global stop_encoding
    if current_pid is not None:
        OnKill.add_pid(current_pid)

    database_helper.set_total_time_compressing(total_time_for_compression)

    if compress_status is None or compress_thread is None:
        return

    if stop_encoding is None:
        return

    if not compress_thread.is_alive():
        return

    stop_encoding = True

    compress_status.shutdown()

    while True:
        if stop_encoding is False:
            break
        time.sleep(status_time)

    compress_status.done_thing(True)
    compress_status._running = False
    compress_status.generate_final_message()


def calculate_efficiency(now: float, prev: float) -> float:
    if -0.1 <= prev <= 0.1:
        return 0

    return (now - prev) / prev


def calculate_average(lst: List[Any]) -> float:
    if not lst:
        return 0
    return sum(lst) / len(lst)


# Copied from https://stackabuse.com/covariance-and-correlation-in-python/
def covariance(x: List[int], y: List[float]) -> float:
    # Finding the mean of the series x and y
    mean_x = sum(x) / float(len(x))
    mean_y = sum(y) / float(len(y))
    # Subtracting mean from the individual elements
    sub_x = [i - mean_x for i in x]
    sub_y = [i - mean_y for i in y]
    numerator = sum([sub_x[i] * sub_y[i] for i in range(len(sub_x))])
    denominator = len(x) - 1
    cov = numerator / denominator
    return cov


if sys.version_info >= (3, 10):
    # In case of python3.10 use the fast standard library.
    from statistics import covariance  # noqa: F541 F811


class CompressStatus(Thread):
    files: List[PreMediaContainer]
    helper: RequestHelper

    cur_file: Optional[PreMediaContainer]
    cur_file_probe: Optional[Dict[str, Any]]
    ffmpeg: Optional[subprocess.Popen[str]]
    start_time_for_video: Optional[float]

    curr_scores_no_time: List[float]
    curr_scores_with_time: List[float]
    curr_size_regression_estimates: List[float]
    curr_size_regression_frame_estimates: List[int]
    curr_size_estimates: List[float]

    num_under_efficiency_limit: int
    last_text_len: int
    last_file_size_stat: int

    def __init__(self, files: List[PreMediaContainer], helper: RequestHelper) -> None:
        self.files = files
        self.helper = helper
        self.lock = Lock()

        self._running = True
        self._shutdown = False

        self.inefficient_videos = database_helper.get_inefficient_videos()
        self.inefficient_videos_size = 0

        self.total_files_available = len(files)
        self.total_prev_size = 0
        self.total_now_size = 0
        self.total_prev_size_of_compressed = 0
        self.total_cur_size_of_compressed = 0
        self.total_files_done = 0

        for file in files:
            self.total_prev_size += file.size

            actual_file_size = os.stat(file.path).st_size
            self.total_now_size += actual_file_size

            if database_helper.make_inefficient_file_name(file) in self.inefficient_videos:
                self.total_prev_size_of_compressed += file.size
                self.inefficient_videos_size += actual_file_size
                self.total_files_done += 1

            elif actual_file_size != file.size:
                self.total_prev_size_of_compressed += file.size
                self.total_cur_size_of_compressed += actual_file_size
                self.total_files_done += 1

        self.reset_file_values()
        super().__init__(daemon=True)

    def reset_file_values(self) -> None:
        self.cur_file = None
        self.cur_file_probe = None
        self.ffmpeg = None
        self.start_time_for_video = None

        self.curr_scores_no_time = []
        self.curr_scores_with_time = []
        self.curr_size_regression_estimates = []
        self.curr_size_regression_frame_estimates = []
        self.curr_size_estimates = []

        self.num_under_efficiency_limit = 0
        self.last_text_len = 0
        self.last_file_size_stat = 1

    def done_thing(self, was_successful: bool) -> None:
        global total_time_for_compression

        with self.lock:
            if self.start_time_for_video is not None:
                total_time_for_compression += int(time.perf_counter() - self.start_time_for_video)
                database_helper.set_total_time_compressing(total_time_for_compression)

            if self.cur_file is None:
                return

            old_file_size = self.cur_file.size
            new_file_size = os.stat(make_temp_filename(self.cur_file) if was_successful else self.cur_file.path).st_size

            self.reset_file_values()

            self.total_now_size -= old_file_size
            self.total_now_size += new_file_size

            self.total_prev_size_of_compressed += old_file_size
            self.total_cur_size_of_compressed += new_file_size

            self.total_files_done += 1

    def start_thing(self, file: PreMediaContainer, ffmpeg: subprocess.Popen[str]) -> None:
        with self.lock:
            self.cur_file = file
            self.cur_file_probe = do_ffprobe(file.path)
            self.ffmpeg = ffmpeg
            self.start_time_for_video = time.perf_counter()

    def shutdown(self) -> None:
        self._shutdown = True

    @staticmethod
    def kill_current() -> None:
        if current_pid is not None:
            try:
                os.kill(current_pid, signal.SIGABRT)
            except Exception:
                pass

    def run(self) -> None:
        global total_time_for_compression
        try:
            while self._running:

                time.sleep(status_time)

                log_strings = [
                    f"Total time: "
                    f"{format_seconds(total_time_for_compression + (time.perf_counter() - self.start_time_for_video) if self.start_time_for_video is not None else total_time_for_compression)}",
                    f"Total videos: {self.total_files_done} / {self.total_files_available}",
                    f"Total time / GB: {total_time_for_compression / max((self.total_prev_size_of_compressed / 1024 ** 3), 1):.2f}s",
                    "",
                    "Total size before compression:  " + HumanBytes.format_pad(self.total_prev_size),
                    "Total size after  compression:  " + HumanBytes.format_pad(self.total_now_size),
                    "Total size done:                " + HumanBytes.format_pad(self.total_prev_size_of_compressed),
                    "Total size remaining:           " + HumanBytes.format_pad(self.total_prev_size - self.total_prev_size_of_compressed),
                    "Total size of compressed files: " + HumanBytes.format_pad(self.total_cur_size_of_compressed),
                    "",
                    f"Global efficiency: {calculate_efficiency(self.total_cur_size_of_compressed, self.total_prev_size_of_compressed) * 100:.2f}%",
                    "",
                    f"Total skipped files: {len(self.inefficient_videos)}",
                    f"Total skipped file size: {HumanBytes.format_str(self.inefficient_videos_size)}",
                    "",
                    "",
                    "Currently processing:",
                    f"{self.cur_file._name}" if self.cur_file is not None else 'None',
                    "",
                ]

                with self.lock:
                    if self.ffmpeg is not None and self.ffmpeg.stderr is not None and self.cur_file_probe is not None:
                        ffmpeg_out = self.ffmpeg.stderr.readline()
                        if ffmpeg_out:
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

                            # Make sure all needed information exists
                            if frame is not None and fps is not None and self.cur_file is not None and video_stream is not None and 'nb_frames' in video_stream and 'duration' in video_stream:

                                cur_file = self.cur_file
                                total_frames = int(video_stream['nb_frames'])
                                prev_size = os.stat(cur_file.path).st_size
                                try:
                                    current_size = os.stat(make_temp_filename(cur_file)).st_size
                                except OSError:
                                    current_size = prev_size

                                # Only update once ffmpeg has written the buffer
                                if current_size > self.last_file_size_stat:
                                    self.curr_size_regression_estimates.append(current_size)
                                    self.curr_size_regression_frame_estimates.append(frame)
                                    self.last_file_size_stat = current_size

                                if len(self.curr_size_regression_estimates) >= 2:
                                    # Textbook linear regression
                                    slope = covariance(self.curr_size_regression_frame_estimates, self.curr_size_regression_estimates) / variance(self.curr_size_regression_frame_estimates)
                                    offset = mean(self.curr_size_regression_estimates) - slope * mean(self.curr_size_regression_frame_estimates)

                                    _estimated_file_size = slope * total_frames + offset
                                    if _estimated_file_size < 0:
                                        _estimated_file_size = 0

                                    _estimated_file_perc = calculate_efficiency(_estimated_file_size, float(prev_size))

                                    estimated_file_size: Optional[float] = _estimated_file_size
                                    estimated_file_perc: Optional[float] = _estimated_file_perc

                                    self.curr_size_estimates.append(_estimated_file_perc)
                                else:
                                    estimated_file_size = None
                                    estimated_file_perc = None

                                perc_done_file = frame / max(total_frames, 1)
                                current_file_stdev = stdev(self.curr_size_estimates[-compress_std_mavg_size:]) if len(self.curr_size_estimates) > 2 else None

                                if estimated_file_perc is not None and current_file_stdev is not None:
                                    # Calculate the compression score
                                    _compression_score_no_time = (1 + estimated_file_perc) ** 0.5 / math.log(1.65 + current_file_stdev)
                                    _compression_score = _compression_score_no_time - 0.5 * perc_done_file ** 0.5

                                    if current_file_stdev < compress_minimum_stdev:
                                        self.curr_scores_no_time.append(_compression_score_no_time)
                                        self.curr_scores_with_time.append(_compression_score)

                                    # Maybe stop the processing of the current file
                                    if self.curr_scores_with_time and current_file_stdev < compress_minimum_stdev:
                                        compression_score = calculate_average(self.curr_scores_with_time[-compress_score_mavg_size:])

                                        if compression_score > compress_minimum_score:
                                            self.num_under_efficiency_limit += 1

                                        if (compression_score > compress_insta_kill_score and len(self.curr_scores_with_time) >= compress_duration_for_insta_kill / status_time) \
                                                or self.num_under_efficiency_limit * status_time > compress_duration_for_to_low_efficiency:
                                            database_helper.update_inefficient_videos(cur_file, estimated_file_perc)
                                            self.inefficient_videos[database_helper.make_inefficient_file_name(cur_file)] = estimated_file_perc
                                            self.inefficient_videos_size += prev_size
                                            self.kill_current()

                                # Use the information to produce the status information

                                log_strings.append(f"Percent done: {perc_done_file * 100:.2f}%")
                                log_strings.append(f"Finished in:  {format_seconds((total_frames - frame) / fps) if fps > 0.1 else '∞'}")
                                log_strings.append(f"Time elapsed: {format_seconds(time.perf_counter() - self.start_time_for_video) if self.start_time_for_video is not None else ''}")

                                log_strings.append("")
                                log_strings.append(f"Original  file size: {HumanBytes.format_pad(prev_size)}")
                                log_strings.append(f"Current   file size: {HumanBytes.format_pad(current_size)}")
                                log_strings.append(f"Estimated file size: {HumanBytes.format_pad(estimated_file_size)}")
                                log_strings.append("")

                                if estimated_file_perc is not None:
                                    log_strings.append(f"Estimated efficiency: {estimated_file_perc * 100:6.2f}%")
                                else:
                                    log_strings.append("Estimated efficiency:   ?")

                                if self.curr_scores_with_time:
                                    log_strings.append(f"Compression score:    {calculate_average(self.curr_scores_no_time[-compress_score_mavg_size:]):6.2f}")
                                else:
                                    log_strings.append("Compression score:      ?")

                    if self._shutdown:
                        log_strings.extend(["", "Please wait for the compression to finish ..."])

                    log_strings.extend(["" for _ in range(self.last_text_len - len(log_strings))])

                    if self._running:
                        self.last_text_len = print_log_messages(log_strings, self.last_text_len)

        except Exception:
            generate_error_message()

    def generate_final_message(self) -> None:
        # TODO: Make better

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
                               f"{HumanBytes.format_pad(prev_size)} → {HumanBytes.format_pad(cur_size)}  ({calculate_efficiency(cur_size, prev_size) * 100:.2f}%)")

        print_log_messages(log_strings, 0)


def compress(files: List[PreMediaContainer]) -> None:
    assert compress_status is not None

    try:
        global stop_encoding
        global current_pid
        check_ffmpeg_exists()

        stop_encoding = False

        # Windows does not support preexec_fn and os.setpgrp() ...
        if sys.platform == "win32":
            popen = partial(subprocess.Popen)
        else:
            popen = partial(subprocess.Popen, preexec_fn=lambda: os.setpgrp())

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

            ffmpeg = popen([
                "ffmpeg",
                "-i", file.path,
                "-y", "-loglevel", "warning", "-stats",
                *ffmpeg_args,
                "-x265-params", "log-level=0",
                new_file_name
            ], stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True)
            current_pid = ffmpeg.pid

            compress_status.start_thing(file, ffmpeg)
            ret_code = ffmpeg.wait()

            compress_status.done_thing(ret_code == 0)

            if ret_code == 0:
                os.replace(new_file_name, file.path)
            else:
                try:
                    os.remove(new_file_name)
                except OSError:
                    pass

        stop_encoding = False

    except Exception:
        generate_error_message()


def calculate_abort_score() -> None:
    current_file_stdev = 0.1
    for estimated_file_perc in np.arange(-0.7, -0, 0.1):
        for perc_done_file in np.arange(0, 1, 0.1):
            premature_abort_score = (1 + estimated_file_perc) ** 0.5 / math.log(1.65 + current_file_stdev) - 0.5 * perc_done_file ** 0.5
            print(f"{estimated_file_perc = :.2f}, {perc_done_file = :.2f}, {current_file_stdev = :.2f}: {premature_abort_score:.2f}")
        print()

    exit(0)


def main() -> None:
    global compress_status
    global compress_thread
    global total_time_for_compression

    acquire_file_lock_or_exit()
    if is_first_time:
        print("\nAttention: Dont rename you video files please!")
        print("Press enter to continue ...\n")
        input()

    total_time_for_compression = database_helper.get_total_time_compressing()
    user = get_credentials()
    pre_status.start()
    helper = RequestHelper(user)

    _content = helper.download_content()
    pre_status.stop()
    print("\n\nProcessing ...\n")

    _content = list(filter(lambda x: x.is_video and x.course_id not in {24337} and os.path.exists(x.path), _content))

    if enable_multithread:
        with ThreadPoolExecutor(os.cpu_count()) as ex:
            _ffprobes = list(ex.map(lambda x: do_ffprobe(x.path), _content))
    else:
        _ffprobes = [do_ffprobe(item.path) for item in _content]

    ffprobes = filter(lambda x: x is not None, _ffprobes)
    no_metadata = []
    content_and_score: List[Tuple[PreMediaContainer, int]] = []
    to_inefficient = database_helper.get_inefficient_videos()
    inefficient_videos = []

    for con, ff in zip(_content, ffprobes):
        if database_helper.make_inefficient_file_name(con) in to_inefficient:
            inefficient_videos.append(con)
            continue

        vid_probe = vstream_from_probe(ff)

        if ff is None or vid_probe is None or "bit_rate" not in vid_probe:
            no_metadata.append(con)
            continue

        content_and_score.append((con, int(vid_probe["bit_rate"])))

    content = [item for item, _ in sorted(content_and_score, key=lambda pair: int(pair[1]), reverse=True)]
    content.extend(no_metadata)

    compress_status = CompressStatus(content + inefficient_videos, helper)
    compress_status.start()

    # Run the conversion in a separate thread so, if killed, it will still run
    compress_thread = Thread(target=compress, args=(content,))
    compress_thread.start()
    compress_thread.join()


compress_status: Optional[CompressStatus] = None
compress_thread: Optional[Thread] = None

# TODO:
#   Cur file size info:
#       Better Score:
#           File compression rate base + for time
#
#   Total saved size
#   status none fill with empty
#   What if no database?

# TODO: format_pad in downloader

#   Human readable for compression score

#   Final summary: How many ignored
#
#   Remote compression?

if __name__ == '__main__':
    main()
