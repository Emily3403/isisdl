"""
This file handles all checksums
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Set, BinaryIO, Tuple, Union, Optional, List

import isis_dl.backend.api as api
from isis_dl.share.settings import checksum_file, checksum_num_bytes, checksum_algorithm


@dataclass
class CheckSumHandler:
    parent_course: api.Course
    checksums: Set[str] = field(default_factory=lambda: set())
    autoload_checksums: bool = True

    def add(self, checksum: str):
        self.checksums.add(checksum)

    def maybe_get_chunk(self, f: BinaryIO, filename: str) -> Tuple[str, Optional[bytes]]:
        checksum, chunk = self.calculate_checksum(f, filename)
        if checksum in self.checksums:
            return checksum, None

        return checksum, chunk

    # TODO: Really dynamic calculation of checksum based on the first 64, 512, … bytes → is this too much overhead?
    def calculate_checksum(self, f: BinaryIO, filename: str) -> Tuple[str, bytes]:
        skip, stop = self._generate_size_from_file(filename)

        def ensure_read(size: Union[int, None]) -> bytes:
            # God this reminds me of c-networking…
            buf: List[bytes] = []  # Avoid copying the string again and again with +=

            if size is None:
                return f.read()

            remaining = size
            while remaining > 0:
                new = f.read(remaining)
                if len(new) == 0:
                    # No file left
                    break

                buf.append(new)
                remaining -= len(new)

            return b"".join(buf)

        ignored = ensure_read(skip)
        chunk = ensure_read(stop)

        if not chunk:
            logging.error(f"The chunk is empty. This means too much of the {filename = } was ignored. I am using a hash of b\"\" and hoping there aren't any collisions!")

        hash_value = checksum_algorithm(chunk).hexdigest()

        return hash_value, ignored + chunk

    @staticmethod
    def _generate_size_from_file(filename: str) -> Tuple[int, Optional[int]]:
        return checksum_num_bytes.get(os.path.splitext(filename)[1]) or checksum_num_bytes[None]

    def __post_init__(self):
        if self.autoload_checksums:
            self.load()

    def __contains__(self, item):
        return item in self.checksums

    def dump(self):
        with open(self.parent_course.path(checksum_file), "w") as f:
            json.dump(sorted(list(self.checksums)), f, indent=4)

    def load(self):
        try:
            with open(self.parent_course.path(checksum_file)) as f:
                self.checksums.update(json.load(f))
        except FileNotFoundError:
            pass
