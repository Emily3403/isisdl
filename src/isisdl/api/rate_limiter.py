from __future__ import annotations

import asyncio
import sys
from asyncio import get_event_loop, create_task, Condition, Task, Event, wait_for
from dataclasses import dataclass, field

from typing_extensions import Self

from isisdl.api.models import MediaType, Course
from isisdl.settings import download_chunk_size, token_queue_refresh_rate, token_queue_bandwidths_save_for, DEBUG_ASSERTS, debug_cycle_time_deviation_allowed, is_windows
from isisdl.utils import normalize, get_async_time, T


@dataclass
class Token:
    num_bytes: int = field(default=download_chunk_size)


class ThrottleDict(dict[MediaType, T]):
    def __init__(self, it: dict[MediaType, T]) -> None:
        super().__init__(it)
        self.assert_valid_state()

    def __setitem__(self, key: MediaType, value: T) -> None:
        super().__setitem__(key, value)
        self.assert_valid_state()

    def __delitem__(self, key: MediaType) -> None:
        super().__delitem__(key)
        self.assert_valid_state()

    def assert_valid_state(self) -> None:
        if DEBUG_ASSERTS:
            assert set(self.keys()) == set(MediaType)

    @classmethod
    def from_default(cls, default: T) -> ThrottleDict[T]:
        return cls({it: default for it in MediaType})


class RateLimiter:
    """
    This class acts as a rate limiter by handing out tokens to async tasks.
    Each token contains a fixed number of bytes, `num_bytes`, which you can then download from it.

    The control flow from a calling Task is meant as follows:

    1. Register the course with `.register_course()`, making your course the least prioritized course to be downloaded
    2. Register your url with the `.register_url()` method.
    3. Establish the TCP connection to the server
    4. Download the file
      - Obtain a token by calling the `.get` method
      - Download the specified amount of bytes
      - Return the token by calling the `.return_token` method
    5. Mark the task as completed by calling the `.complete_url()` method
    6. Upon finishing downloading the entire course, complete it with `.complete_course()`.

    The fundamental idea of rate limiting is having reserved capacities per MediaType, and carrying the not-used tokens into the next round with
    num_tokens_remaining_from_last_iteration, letting the video download consume the remains of the last iteration.

    Fundamentally, a compromise between handing out tokens prematurely in order to maximize bandwidth and slow download servers has to be made.
    Assuming external links, a .get can easily take upwards of 10 seconds. We want to prioritize these slow downloads as they make up, especially at the end,
    the biggest time consumption. However, we also want to spend the tokens of the MediaType.extern if they are not used up as they make up a significant percentage of the total tokens.

    Thus, we must always reserve a few tokens for slow downloads, but also use all of them eventually.
    """

    rate: int | None
    num_tokens_remaining_from_last_iteration: int
    last_update: float

    depleted_tokens: ThrottleDict[int]  # Captures how many tokens per category were depleted
    buffer_sizes: ThrottleDict[float]  # Percentage of how much capacity is reserved for each category

    courses: dict[int, Course]
    urls: ThrottleDict[int]

    # min 1 Condition per Course, notify one url of the waiting urls for the course
    # somehow iteration by course, by url (both sorted) has to be possible. Then, notify each url to continue if capacity remains
    # uncouple the token timewindow from the loop rate. When the loop rate is significantly higher, it should be possible to hand out all tokens

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

        self.courses = {}
        self.urls = ThrottleDict.from_default(0)

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

        # The idea is to assign, for each MediaType that is waiting, a number.
        # Then, after all assignments have been made, the resulting dictionary is normalized to a percentage.

        def maybe(num: int, tt: MediaType) -> int:
            return num if self.urls[tt] else 0

        buffer_sizes = {
            MediaType.extern: maybe(100, MediaType.extern),
            MediaType.document: maybe(50, MediaType.document),
            MediaType.video: maybe(10, MediaType.video),
            # TODO: How do I do the free_for_all thing?
        }

        normalized_buffer_sizes = normalize(buffer_sizes)
        # if isclose(sum(normalized_buffer_sizes.values()), 0):
        #     normalized_buffer_sizes[MediaType.free_for_all] = 1

        self.buffer_sizes = ThrottleDict(normalized_buffer_sizes)

    async def register_course(self, course: Course) -> None:
        """
        Only a certain number of courses may be downloaded at once
        """
        while len(self.courses) > 2:
            await asyncio.sleep(5)

        self.courses[course.id] = course

    def complete_course(self, course: Course) -> None:
        del self.courses[course.id]

    async def register_url(self, course: Course, media_type: MediaType) -> None:
        while sum(self.urls.values()) > 5:
            await asyncio.sleep(1)

        self.urls[media_type] += 1
        self.recalculate_buffer_sizes()

    def complete_url(self, course: Course, media_type: MediaType) -> None:
        self.urls[media_type] -= 1
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
        # TODO: Test how long a loop takes and what that means for sleep times
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

                # TODO: This is not quite accurate. What if the download only has a small chunk left?
                num_bytes_downloaded_since_last_update = sum(it.num_bytes for it in self.returned_tokens)
                self.bytes_downloaded = self.bytes_downloaded[-num_to_keep_in_bytes_downloaded:]
                self.bytes_downloaded.append(num_bytes_downloaded_since_last_update)

                self.last_update = get_async_time(event_loop)
                self.refill_condition.notify()

            # Finally, compute how much time we've spent doing this stuff and sleep the remainder.
            await asyncio.sleep(max(token_queue_refresh_rate - (event_loop.time() - start), 0))

            # TODO: Temp testing
            if is_windows:
                return

    def return_token(self, token: Token) -> None:
        self.returned_tokens.append(token)

    def is_able_to_obtain_token(self, media_type: MediaType) -> bool:
        if self.rate is None:
            return True

        max_num_tokens = self.calculate_max_num_tokens()

        def can_obtain(it: MediaType) -> bool:
            return self.depleted_tokens[it] < self.buffer_sizes[it] * max_num_tokens

        # As a first step try the free_for_all buffer. It should always be depleted first.
        # if can_obtain(MediaType.free_for_all):
        #     return True

        # Otherwise, check the MediaType specific buffer
        return can_obtain(media_type)

    async def get(self, media_type: MediaType) -> Token | None:
        token = await self._get(media_type, block=True)
        if DEBUG_ASSERTS:
            assert token is not None

        return token

    async def get_nonblock(self, media_type: MediaType) -> Token | None:
        return await self._get(media_type, block=False)

    async def _get(self, media_type: MediaType, block: bool = True) -> Token | None:
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

            # TODO: What if .is_able_to_obtain_token did a ffa one?
            self.depleted_tokens[media_type] += 1
            return Token()

    async def used_bandwidth(self) -> float:
        async with self.refill_condition:
            return sum(self.bytes_downloaded) / token_queue_bandwidths_save_for
