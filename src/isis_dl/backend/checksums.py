"""
This file handles all checksums
"""
from __future__ import annotations

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Set, BinaryIO, Union, Optional, List, Iterable

import isis_dl.backend.api as api
from isis_dl.backend.downloads import MediaContainer, SessionWithKey
from isis_dl.share.settings import checksum_file, checksum_num_bytes, checksum_algorithm, ExtensionNumBytes, checksum_range_parameter_ignored, num_sessions, enable_multithread
from isis_dl.share.utils import args, get_url_from_session


@dataclass
class CheckSumHandler:
    parent_course: api.Course
    checksums: Set[str] = field(default_factory=lambda: set())
    autoload_checksums: bool = True

    def add(self, checksum: str):
        self.checksums.add(checksum)

    def already_downloaded(self, file: MediaContainer) -> Optional[str]:
        checksum = self.calculate_checksum(file)
        if not args.overwrite and checksum in self.checksums:
            return None

        return checksum

    def calculate_checksum(self, file: Union[MediaContainer, BinaryIO]) -> str:
        if isinstance(file, MediaContainer):
            return self._calculate_checksum_media_container(file)

        else:
            return self._calculate_checksum_file(file)

    def _calculate_checksum_media_container(self, file: MediaContainer) -> str:
        size = self._generate_size_from_file(file.name)

        chunks = []
        # The isis video server is *really* fast (0.01s latency) and it is the one accepting the range parameter. Thus, it is okay if we discard that request.
        req = get_url_from_session(file.s, file.url, headers={"Range": "bytes=0-1"}, params=file.additional_params_for_request, stream=True)

        if req.status_code == 200 or file.size is None:
            # Fallback for .zip's
            self.ensure_read(req.raw, size.skip_header)
            chunks.append(self.ensure_read(req.raw, checksum_range_parameter_ignored))

        else:
            req.close()

            def download_chunk_with_offset(s: SessionWithKey, offset: int):
                req = get_url_from_session(s, file.url, headers={"Range": f"bytes={offset}-{offset + size.num_bytes_per_point - 1}"}, stream=True, params=file.additional_params_for_request)
                # bts = self.ensure_read(req.raw, size.num_bytes_per_point)
                bts = req.raw.read(size.num_bytes_per_point)
                req.close()
                return bts

            if file.size is None:
                # I would like to implement an algorithm to estimate the file size based on exponential trial-and-error.
                # This task, however, is inherently single-threaded since the next iteration is only done when the last one did not fail.
                # If I would implement it like that it would take *way* to long.

                # And, since `file.size` is (based on my current testing) never None, it is pretty useless. This could be a fun experiment tho.
                pass

            base_skip = file.size // (size.num_data_points - 1)

            sessions = random.sample(api.CourseDownloader.sessions, size.num_data_points)

            if enable_multithread:
                with ThreadPoolExecutor(num_sessions) as ex:
                    chunks.extend(list(ex.map(download_chunk_with_offset, sessions, range(size.skip_header, file.size - size.skip_footer, base_skip))))

            else:
                for session, offset in zip(sessions, range(size.skip_header, file.size - size.skip_footer, base_skip)):
                    chunks.append(download_chunk_with_offset(session, offset))

        return self.calculate_hash(chunks)

    def _calculate_checksum_file(self, file: BinaryIO) -> str:
        size = self._generate_size_from_file(file.name)

        chunks = []
        file_size = os.path.getsize(file.name)
        base_skip = file_size // (size.num_data_points - 1)
        for offset in range(size.skip_header, file_size - size.skip_footer, base_skip):
            file.seek(offset)
            chunks.append(self.ensure_read(file, size.num_bytes_per_point))

        if "online-tutorium-3.pdf" in file.name:
            for row in chunks:
                print(" ".join(str(item) for item in row))

        return self.calculate_hash(chunks)

    @staticmethod
    def calculate_hash(chunks: Iterable[bytes]) -> str:
        return checksum_algorithm(b"".join(chunks)).hexdigest()

    @staticmethod
    def ensure_read(f: BinaryIO, size: Optional[int] = None) -> bytes:
        # God this reminds me of c-networking…
        buf: List[bytes] = []  # Avoid copying the string again and again with +=

        if size is None:
            return f.read()

        remaining = size
        while True:
            new = f.read(remaining)
            remaining -= len(new)
            buf.append(new)

            if remaining == 0 or len(new) == 0:
                # No file left
                break

        return b"".join(buf)

    @staticmethod
    def _generate_size_from_file(name: str) -> ExtensionNumBytes:
        return checksum_num_bytes.get(os.path.splitext(name)[1]) or checksum_num_bytes[None]

    def __post_init__(self):
        if self.autoload_checksums:
            self.load()

    def __contains__(self, item):
        return item in self.checksums

    def dump(self):
        with open(self.parent_course.path(checksum_file), "w") as f:
            json.dump(list(self.checksums), f, indent=4, sort_keys=True)

    def load(self):
        try:
            with open(self.parent_course.path(checksum_file)) as f:
                self.checksums.update(json.load(f))
        except (FileNotFoundError, JSONDecodeError):
            pass
