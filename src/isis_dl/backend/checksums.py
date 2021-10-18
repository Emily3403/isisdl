"""
This file handles all checksums and stuff
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Set, BinaryIO, Tuple, Union, Optional

import isis_dl.backend.api as api
from isis_dl.share.settings import checksum_file, checksum_num_bytes


@dataclass
class CheckSumHandler:
    parent_course: api.Course
    checksums: Set[str] = field(default_factory=lambda: set())
    autoload_checksums: bool = True

    def add(self, checksum: str):
        self.checksums.add(checksum)

    def maybe_get_chunk(self, f: BinaryIO, filename: str) -> Union[Tuple[str, bytes], Tuple[str, None]]:
        checksum, chunk = self._calculate_checksum(f, filename)
        if checksum in self.checksums:
            return checksum, None

        self.add(checksum)
        return checksum, chunk

    def _calculate_checksum(self, f: BinaryIO, filename: str) -> Tuple[str, bytes]:
        # TODO: Does f.read(…) ensure exact number of bytes?
        start, stop = self._generate_size_from_file(filename)

        def ensure_read(size: Union[int, None]) -> bytes:
            # God this reminds me of c-networking…
            buf = b""

            if size is None:
                return f.read()

            else:
                remaining = size
                while remaining > 0:
                    new = f.read(remaining)
                    if len(new) == 0:
                        logging.error(f"No file left: {filename}")
                        break

                    buf += new
                    remaining -= len(new)

                return buf

        skip = ensure_read(start)
        chunk = ensure_read(stop)

        hash_value = sha256(chunk).hexdigest()

        return hash_value, skip + chunk

    def _generate_size_from_file(self, filename: str) -> Tuple[int, Optional[int]]:
        return checksum_num_bytes.get(os.path.splitext(filename)[1]) or checksum_num_bytes[None]

    def __post_init__(self):
        if self.autoload_checksums:
            self.load()

    def __contains__(self, item):
        return item in self.checksums

    def dump(self):
        with open(self.parent_course.path(checksum_file), "w") as f:
            json.dump(list(self.checksums), f, indent=4)

    def load(self):
        try:
            with open(self.parent_course.path(checksum_file)) as f:
                self.checksums.update(json.load(f))
        except FileNotFoundError:
            pass
