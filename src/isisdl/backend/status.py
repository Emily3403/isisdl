# TODO: Syntactic sugar: define __exit__ and __enter__ for `with SyncStatus():`
from __future__ import annotations

import datetime
import enum
import shutil
import time
from threading import Thread, Lock
from typing import List, Optional, Dict, Any, TYPE_CHECKING

import math

from isisdl.utils import clear, HumanBytes, args, MediaType, DownloadThrottler
from isisdl.settings import status_chop_off, is_windows, status_time, status_progress_bar_resolution, download_progress_bar_resolution

if TYPE_CHECKING:
    from isisdl.backend.request_helper import MediaContainer


def maybe_chop_off_str(st: str, width: int) -> str:
    if len(st) > width - status_chop_off + 1:
        return str(st[:width - status_chop_off] + "." * status_chop_off)
    return st.ljust(width)


def print_log_messages(strings: List[str], last_num: int) -> int:
    if last_num:
        if is_windows:
            # Windows does not support ANSI escape sequences…
            clear()
        else:
            print(f"\033[{last_num}F", end="")

    # First sanitize the output
    width = shutil.get_terminal_size().columns

    for i, item in enumerate(strings):
        strings[i] = maybe_chop_off_str(item, width)

    final_str = "\n".join(strings)
    print(final_str)

    # Erase all previous chars
    return final_str.count("\n") + 1


class Status(Thread):
    total: Optional[int]

    message: str = "Doing stuff..."
    count: Optional[int] = None
    _progress_bar: bool = True
    _i = 0
    _last_text_len = 0
    _running = True
    _lock = Lock()

    def __init__(self, total: Optional[int] = None) -> None:
        self.count = 0
        self.total = total

        super().__init__(daemon=True)

    def __enter__(self) -> Any:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # TODO: Figure out type
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        while self._running:
            log_strings = ["", self.message + " " + "." * self._i, ""]
            log_strings.extend(self.generate_log_message())

            if self._progress_bar and self.count is not None and self.total is not None:
                perc_done = int(self.count / self.total * status_progress_bar_resolution)
                log_strings.append(f"[{'█' * perc_done}{' ' * (status_progress_bar_resolution - perc_done)}]")

            log_strings.append("")
            if self._running:
                self._last_text_len = print_log_messages(log_strings, self._last_text_len)

            self._i = (self._i + 1) % 4
            time.sleep(status_time)

    def generate_log_message(self) -> List[str]:
        return []

    def add(self, *args: Any, **kwargs: Any) -> None:
        # self.count += 1
        ...

    def done(self, *args: Any, **kwargs: Any) -> None:
        if self.count is not None:
            self.count += 1


# TODO: When already done file add them in the beginning instead of subtracting: 0 / 300 → 200 / 500
class DownloadStatus(Status):
    message = "Downloading videos"
    _progress_bar = False

    def __init__(self, files: List[MediaContainer], num_threads: int, throttler: DownloadThrottler):
        self.files = files
        self.finished_files = 0
        self.total_size = sum(item.size for item in files if item.size != -1)
        self.total_downloaded = 0

        self.num_threads = num_threads
        self.throttler = throttler

        self.thread_files: Dict[int, Optional[MediaContainer]] = {i: None for i in range(num_threads)}
        self.stream_file: Optional[MediaContainer] = None
        super().__init__(len(files))

    def add_container(self, thread_id: int, container: MediaContainer) -> None:
        self.thread_files[thread_id] = container

    def add_streaming(self, container: MediaContainer) -> None:
        self.stream_file = container

    def done_streaming(self) -> None:
        self.stream_file = None

    def done(self, thread_num: int, container: MediaContainer, *args: Any, **kwargs: Any) -> None:  # type: ignore
        with self._lock:
            item = self.thread_files[thread_num]
            self.thread_files[thread_num] = None

            if item is None:
                return

            self.finished_files += 1

            if item.current_size is not None:
                self.total_downloaded += item.current_size
            elif item._stop:
                self.total_downloaded += item.size

    def progress_bar_container(self, container: MediaContainer) -> str:
        if container.size in {0, -1}:
            percent: float = 0
        elif container.current_size is None:
            percent = 0
        else:
            percent = container.current_size / container.size

        # Sometimes this bug happens… I don't know why
        if percent > 1:
            percent = 1

        progress_chars = int(percent * download_progress_bar_resolution)
        return "╶" + "█" * progress_chars + " " * (download_progress_bar_resolution - progress_chars) + "╴"

    def generate_log_message(self) -> List[str]:
        log_strings = []
        curr_bandwidth = HumanBytes.format_str(self.throttler.bandwidth_used)
        total_size = HumanBytes.format_str(self.total_size)

        downloaded_bytes = self.total_downloaded + sum(item.current_size for item in self.thread_files.values() if item is not None and item.current_size is not None)

        log_strings.append("")
        log_strings.append(f"Current bandwidth usage: {curr_bandwidth}/s {f'(throttled to {self.throttler.download_rate} MiB)' if self.throttler.download_rate != -1 else ''}")

        if args.stream:
            log_strings.append("")
            if self.stream_file is not None:
                log_strings.append(f"Stream: {self.progress_bar_container(self.stream_file)} "
                                   f"[ {HumanBytes.format_pad(self.stream_file.current_size)} | {HumanBytes.format_pad(self.stream_file.size)} ] - {self.stream_file.path}")
            else:
                log_strings.append("Stream: Waiting")
        else:
            # General meta-info
            log_strings.append(f"Downloaded {HumanBytes.format_str(downloaded_bytes)} / {total_size}")
            log_strings.append(f"Finished:  {self.finished_files} / {len(self.files)} files")
            log_strings.append(f"ETA: {datetime.timedelta(seconds=int((self.total_size - downloaded_bytes) / max(self.throttler.bandwidth_used, 1)))}")
            log_strings.append("")

            # Now determine the already downloaded amount and display it
            thread_format = math.ceil(math.log10(len(self.thread_files) or 1))
            for thread_id, container in self.thread_files.items():
                thread_string = f"Thread {thread_id:{' '}<{thread_format}}"
                if container is None:
                    log_strings.append(thread_string)
                    continue

                log_strings.append(
                    f"{thread_string} {self.progress_bar_container(container)} [ {HumanBytes.format_pad(container.current_size)} | {HumanBytes.format_pad(container.size)} ] - {container.path}")
                pass

            # Optional streaming info
            if self.stream_file is not None:
                log_strings.append("")
                log_strings.append(
                    f"Stream:  {self.progress_bar_container(self.stream_file)} [ {HumanBytes.format_pad(self.stream_file.current_size)} | {HumanBytes.format_pad(self.stream_file.size)} ]"
                    f" - {self.stream_file.path}")
            else:
                log_strings.extend(["", ""])

        return log_strings


class SyncStatus(Status):
    message = "Discovering files"

    def generate_log_message(self) -> List[str]:
        return []


# TODO: When sync-ing after lot of deleting the progress bar becomes large.
class StatusOptions(enum.Enum):
    startup = 0
    authenticating = 1
    getting_content = 2
    getting_extern = 3
    done = 4


class RequestHelperStatus(Status):
    status: StatusOptions

    def __init__(self) -> None:
        self.set_status(StatusOptions.startup)
        super().__init__()

    def set_total(self, total: int) -> None:
        self.total = total

    def set_status(self, status: StatusOptions) -> None:
        self._i = 0
        self.status = status
        self.count = 0 if status == StatusOptions.getting_content or status == StatusOptions.getting_extern else None

        if self.status == StatusOptions.startup:
            self.message = "Starting up"

        elif self.status == StatusOptions.authenticating:
            self.message = "Authenticating with ISIS"

        elif self.status == StatusOptions.getting_content:
            self.message = "Getting the content of the Courses"

        elif self.status == StatusOptions.getting_extern:
            # TODO: This is not accurate
            self.message = "Sending webrequests to external websites for additional content"

        else:
            self.message = ""

    def generate_log_message(self) -> List[str]:
        if self.status != StatusOptions.getting_extern:
            return []

        from isisdl.backend.request_helper import external_links, MediaContainer
        video_done, video_total, extern_done, extern_total = 0, 0, 0, 0

        for link in external_links:
            container = MediaContainer.from_dump(link.url)

            if link.media_type == MediaType.video:
                video_total += 1
                if container is not True:
                    video_done += 1

            elif link.media_type == MediaType.extern:
                extern_total += 1
                if container is not True:
                    extern_done += 1

        return [
            f"({video_done:>{int(math.log10(video_total or 1)) + 1}} / {video_total} videos, "
            f"{extern_done:>{int(math.log10(extern_total or 1))}} / {extern_total} external links, will be cached)", ""
        ]
