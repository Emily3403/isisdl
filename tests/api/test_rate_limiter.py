import asyncio
import random
from asyncio import Condition, get_event_loop

import pytest

from isisdl.api.rate_limiter import RateLimiter, ThrottleType, ThrottleDict
from isisdl.settings import token_queue_refresh_rate, debug_cycle_time_deviation_allowed, token_queue_bandwidths_save_for


def test_throttle_dict() -> None:
    it = ThrottleDict({it: random.randint(-999, 999) for it in ThrottleType})

    with pytest.raises(AssertionError):
        it[1] = 5  # type:ignore[index]

    with pytest.raises(AssertionError):
        del it[ThrottleType.free_for_all]


@pytest.mark.asyncio
async def test_rate_limiter_reset_locks_works() -> None:
    limiter = RateLimiter(10, _condition=Condition())

    async with limiter.refill_condition:
        last_update = limiter.last_update
        await asyncio.sleep(3 * token_queue_refresh_rate)
        assert last_update == limiter.last_update

    with pytest.raises(AssertionError):
        # The debug assert in the rate limiter should have triggered
        await limiter.finish()


def num_tokens_should_be_able_to_obtain(limiter: RateLimiter, media_types: list[ThrottleType]) -> float:
    return sum(limiter.buffer_sizes[it] for it in media_types) * limiter.calculate_max_num_tokens()


@pytest.mark.asyncio
async def test_rate_limiter_buffer_sizes_work() -> None:
    the_rate = 10
    limiter = RateLimiter(the_rate, _condition=Condition())
    max_num_tokens = limiter.calculate_max_num_tokens()

    # When no ThrottleType is registered, all tokens should be obtainable from `ThrottleType.free_for_all`
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.free_for_all]) == max_num_tokens

    # Now, only 1 extern ThrottleType is waiting. It should have full priority.
    limiter.register(ThrottleType.extern)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) == max_num_tokens

    for _ in range(10):
        limiter.register(ThrottleType.extern)
        assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) == max_num_tokens

    limiter.register(ThrottleType.document)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.document, ThrottleType.extern]) == max_num_tokens

    limiter.register(ThrottleType.video)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern, ThrottleType.document]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern, ThrottleType.document, ThrottleType.video]) == max_num_tokens

    limiter.register(ThrottleType.free_for_all)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern, ThrottleType.document]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern, ThrottleType.document, ThrottleType.video]) == max_num_tokens

    limiter.completed(ThrottleType.video)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) != max_num_tokens
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern, ThrottleType.document]) == max_num_tokens

    limiter.completed(ThrottleType.document)
    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.extern]) == max_num_tokens

    for _ in range(11):
        limiter.completed(ThrottleType.extern)

    assert num_tokens_should_be_able_to_obtain(limiter, [ThrottleType.free_for_all]) == max_num_tokens

    await limiter.finish()


async def consume_tokens(limiter: RateLimiter, num: int, media_type: ThrottleType = ThrottleType.free_for_all) -> None:
    for _ in range(num):
        it = await limiter.get_nonblock(media_type)
        assert it is not None
        limiter.return_token(it)


async def consume_exact_tokens(limiter: RateLimiter, num: int, media_type: ThrottleType = ThrottleType.free_for_all) -> None:
    await consume_tokens(limiter, num)
    assert await limiter.get_nonblock(media_type) is None


@pytest.mark.asyncio
async def test_rate_limiter_get_works() -> None:
    limiter = RateLimiter(10, _condition=Condition())

    async with limiter.refill_condition:
        last_update = limiter.last_update
        await consume_exact_tokens(limiter, limiter.calculate_max_num_tokens())
        assert limiter.last_update == last_update

    await limiter.finish()


@pytest.mark.asyncio
async def test_rate_limiter_no_limit() -> None:
    num_tokens_to_consume = 1000
    limiter = RateLimiter(None, _condition=Condition())

    def assert_limiter_state() -> None:
        assert limiter.rate is None
        assert limiter.num_tokens_remaining_from_last_iteration == 0

        assert limiter.depleted_tokens == {it: 0 for it in ThrottleType}
        assert limiter.buffer_sizes == {it: 0 for it in ThrottleType}

    assert_limiter_state()

    async with limiter.refill_condition:
        last_update = limiter.last_update
        await consume_tokens(limiter, num_tokens_to_consume)
        assert_limiter_state()
        assert limiter.last_update == last_update

        await limiter.refill_condition.wait()
        assert limiter.last_update != last_update
        last_update = limiter.last_update
        assert_limiter_state()

        limiter.register(ThrottleType.extern)
        await consume_tokens(limiter, num_tokens_to_consume)
        assert_limiter_state()
        assert limiter.last_update == last_update

    await limiter.finish()


@pytest.mark.asyncio
async def test_rate_limiter_refill_works() -> None:
    limiter = RateLimiter(10, _condition=Condition())

    async with limiter.refill_condition:
        last_update = limiter.last_update
        await consume_exact_tokens(limiter, limiter.calculate_max_num_tokens())
        assert limiter.depleted_tokens[ThrottleType.free_for_all] == limiter.calculate_max_num_tokens()
        assert limiter.last_update == last_update

        await limiter.refill_condition.wait()

        assert limiter.last_update != last_update
        assert limiter.num_tokens_remaining_from_last_iteration == 0
        assert get_event_loop().time() - limiter.last_update <= token_queue_refresh_rate * debug_cycle_time_deviation_allowed
        await consume_exact_tokens(limiter, limiter.calculate_max_num_tokens())

    await limiter.finish()


@pytest.mark.asyncio
async def test_rate_limiter_num_remaining_from_last_iteration_works() -> None:
    the_rate = 10
    limiter = RateLimiter(the_rate, _condition=Condition())

    async with limiter.refill_condition:
        last_update, num_tokens_to_consume = limiter.last_update, limiter.calculate_max_num_tokens() // 2 + random.randint(-10, 10)
        await consume_tokens(limiter, num_tokens_to_consume)
        assert limiter.last_update == last_update
        assert limiter.depleted_tokens[ThrottleType.free_for_all] == num_tokens_to_consume

        await limiter.refill_condition.wait()

        assert limiter.last_update != last_update
        assert get_event_loop().time() - limiter.last_update <= token_queue_refresh_rate * debug_cycle_time_deviation_allowed

        assert limiter.num_tokens_remaining_from_last_iteration == limiter.calculate_max_num_tokens() - num_tokens_to_consume
        await consume_exact_tokens(limiter, limiter.calculate_max_num_tokens() * 2 - num_tokens_to_consume)

    await limiter.finish()


@pytest.mark.asyncio
async def test_rate_limiter_with_bandwidth() -> None:
    the_bandwidth = 10
    limiter = RateLimiter.from_bandwidth(the_bandwidth)

    async def consumer() -> None:
        while True:
            token = await limiter.get(ThrottleType.free_for_all)
            limiter.return_token(token)

    task = asyncio.create_task(consumer())

    await asyncio.sleep(token_queue_bandwidths_save_for)

    assert await limiter.used_bandwidth() >= the_bandwidth * 0.99
    task.cancel()
    await limiter.finish()
