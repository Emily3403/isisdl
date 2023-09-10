from __future__ import annotations

import asyncio
import sys
from asyncio import get_event_loop, create_task, Condition, Task, Event, wait_for
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from typing_extensions import Self

from isisdl.api.models import MediaType
from isisdl.settings import download_chunk_size, token_queue_refresh_rate, token_queue_bandwidths_save_for, DEBUG_ASSERTS, debug_cycle_time_deviation_allowed, is_windows
from isisdl.utils import normalize, get_async_time, T


@dataclass
class Token:
    num_bytes: int = field(default=download_chunk_size)


class ThrottleType(Enum):
    stream = 1
    extern = 2
    document = 3
    video = 4

    # This ThrottleType is used to add an entry in the `buffer_sizes` dict for every ThrottleType to use.
    free_for_all = 5

    @staticmethod
    def from_media_type(it: MediaType) -> ThrottleType:
        match it:
            case MediaType.extern:
                return ThrottleType.extern

            case MediaType.video:
                return ThrottleType.video

            case _:
                return ThrottleType.document


class ThrottleDict(dict[ThrottleType, T]):
    def __init__(self, it: dict[ThrottleType, T]) -> None:
        super().__init__(it)
        self.assert_valid_state()

    def __setitem__(self, key: ThrottleType, value: T) -> None:
        super().__setitem__(key, value)
        self.assert_valid_state()

    def __delitem__(self, key: ThrottleType) -> None:
        super().__delitem__(key)
        self.assert_valid_state()

    def assert_valid_state(self) -> None:
        if DEBUG_ASSERTS:
            assert set(self.keys()) == set(ThrottleType)

    @classmethod
    def from_default(cls, default: T) -> ThrottleDict[T]:
        return cls({it: default for it in ThrottleType})


class RateLimiter:
    """
    This class acts as a rate limiter by handing out tokens to async tasks.
    Each token contains a fixed number of bytes, `num_bytes`, which you can then download from it.

    The control flow from a calling Task is meant as follows:

    1. Register with the `.register()` method.
    2. Establish the TCP connection to the server
    3. Download the file
      - Obtain a token by calling the `.get` method
      - Download the specified amount of bytes
      - Return the token by calling the `.return_token` method
    4. Mark the task as completed by calling the `.complete()` method

    Important caveat: The `asyncio.Condition` is not Thread-safe. Meaning that synchronization will be a problem in the future, if I'm planning on using threads.
    """

    rate: int | None
    num_tokens_remaining_from_last_iteration: int
    last_update: float

    depleted_tokens: ThrottleDict[int]
    buffer_sizes: ThrottleDict[float]  # Percentage
    waiters: ThrottleDict[int]

    returned_tokens: list[Token]
    bytes_downloaded: list[int]  # This list is a collection of how much bandwidth was used over the last n timesteps

    refill_condition: Condition
    get_condition: Condition
    _stop_event: Event
    task: Task[None]

    def __init__(self, num_tokens_per_iteration: int | None, _condition: Condition | None = None):
        # The _condition parameter is _only_ used by the `.get` method. Use it to control the lock yourself while providing a mock Lock to be acquired.
        self.rate = num_tokens_per_iteration
        self.num_tokens_remaining_from_last_iteration = 0

        self.depleted_tokens = ThrottleDict.from_default(0)
        self.buffer_sizes = ThrottleDict.from_default(0)
        self.waiters = ThrottleDict.from_default(0)

        self.bytes_downloaded, self.returned_tokens = [], []
        self.refill_condition = Condition()
        self.get_condition = _condition or self.refill_condition
        self._stop_event = Event()
        self.last_update = get_async_time()

        self.recalculate_buffer_sizes()
        self.task = create_task(self.refill_tokens())  # TODO: How to deal with exceptions. I want to be able to ignore them

    @classmethod
    def from_bandwidth(cls, num_mbits: float, _condition: Condition | None = None) -> Self:
        return cls(int(num_mbits * 1024 ** 2 / download_chunk_size * token_queue_refresh_rate))

    def calculate_max_num_tokens(self) -> int:
        if self.rate is None:
            if DEBUG_ASSERTS:
                assert False

            return sys.maxsize

        return int(self.rate / token_queue_refresh_rate)

    def recalculate_buffer_sizes(self) -> None:
        if self.rate is None:
            return

        # The idea is to assign, for each ThrottleType that is waiting, a number.
        # Then, after all assignments have been made, the resulting dictionary is normalized to a percentage.

        buffer_sizes = {
            ThrottleType.stream: 1000 if self.waiters[ThrottleType.stream] else 0,
            ThrottleType.extern: 100 if self.waiters[ThrottleType.extern] else 0,
            ThrottleType.document: 50 if self.waiters[ThrottleType.document] else 0,
            ThrottleType.video: 10 if self.waiters[ThrottleType.video] else 0,
            ThrottleType.free_for_all: 0,
        }

        normalized_buffer_sizes = normalize(buffer_sizes)
        if sum(normalized_buffer_sizes.values()) == 0:
            normalized_buffer_sizes[ThrottleType.free_for_all] = 1

        self.buffer_sizes = ThrottleDict(normalized_buffer_sizes)

    def register(self, media_type: ThrottleType) -> None:
        self.waiters[media_type] += 1
        self.recalculate_buffer_sizes()

    def completed(self, media_type: ThrottleType) -> None:
        self.waiters[media_type] -= 1
        self.recalculate_buffer_sizes()

    async def finish(self) -> None:
        self._stop_event.set()
        await wait_for(self.task, timeout=2 * token_queue_refresh_rate)

        if DEBUG_ASSERTS:
            assert self.task.done()
            assert self.task.exception() is None

        if not self.task.done():
            self.task.cancel()

    async def refill_tokens(self) -> None:
        event_loop = get_event_loop()
        num_to_keep_in_bytes_downloaded = int(token_queue_bandwidths_save_for / token_queue_refresh_rate)

        while True:

            if self._stop_event.is_set():
                return

            async with self.refill_condition:
                start = get_async_time(event_loop)
                time_between_last_update = start - self.last_update

                if DEBUG_ASSERTS:
                    assert time_between_last_update <= token_queue_refresh_rate * debug_cycle_time_deviation_allowed

                if self.rate is not None:
                    self.num_tokens_remaining_from_last_iteration = int(self.calculate_max_num_tokens()) - sum(it for it in self.depleted_tokens.values())
                    self.depleted_tokens = ThrottleDict.from_default(0)

                num_bytes_downloaded_since_last_update = sum(it.num_bytes for it in self.returned_tokens)
                self.bytes_downloaded = self.bytes_downloaded[-num_to_keep_in_bytes_downloaded:]
                self.bytes_downloaded.append(num_bytes_downloaded_since_last_update)

                self.last_update = get_async_time(event_loop)
                self.refill_condition.notify()

            # Finally, compute how much time we've spent doing this stuff and sleep the remainder.
            await asyncio.sleep(max(token_queue_refresh_rate - (event_loop.time() - start), 0))
            if is_windows:
                return

    def return_token(self, token: Token) -> None:
        self.returned_tokens.append(token)

    def is_able_to_obtain_token(self, media_type: ThrottleType) -> bool:
        if self.rate is None:
            return True

        max_num_tokens = self.calculate_max_num_tokens()

        def can_obtain(it: ThrottleType) -> bool:
            return self.depleted_tokens[it] < self.buffer_sizes[it] * max_num_tokens

        # As a first step try the free_for_all buffer. It should always be depleted first.
        if can_obtain(ThrottleType.free_for_all):
            return True

        # Otherwise, check the ThrottleType specific buffer
        return can_obtain(media_type)

    async def get(self, media_type: ThrottleType) -> Token:
        token = await self._get(media_type, block=True)
        if TYPE_CHECKING or DEBUG_ASSERTS:
            assert token is not None

        return token

    async def get_nonblock(self, media_type: ThrottleType) -> Token | None:
        return await self._get(media_type, block=False)

    async def _get(self, media_type: ThrottleType, block: bool = True) -> Token | None:
        if self.rate is None:
            return Token()

        # TODO: Do i want to trigger the non-blocking behaviour for the get condition?
        if self.get_condition.locked() and block is False:
            return None

        async with self.get_condition:

            # First check if there are tokens left from the last iteration.
            if self.num_tokens_remaining_from_last_iteration > 0:
                self.num_tokens_remaining_from_last_iteration -= 1
                return Token()

            # Now, check the buffers for this iteration.
            while not self.is_able_to_obtain_token(media_type):
                if block is False:
                    return None

                await self.refill_condition.wait()

            self.depleted_tokens[media_type] += 1
            return Token()

    async def used_bandwidth(self) -> float:
        async with self.refill_condition:
            return sum(self.bytes_downloaded) / token_queue_bandwidths_save_for
