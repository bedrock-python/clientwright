"""Per-origin limiters: loop affinity and thread safety."""

from __future__ import annotations

import asyncio
import threading
import time

from clientwright.core.policy.concurrency import AsyncOriginLimiter, SyncOriginLimiter

# --- async limiter ---


def test__sequential_event_loops__do_not_share_bound_semaphores() -> None:
    limiter = AsyncOriginLimiter(limit=1)

    async def contended_use() -> None:
        async def hold() -> None:
            async with limiter.acquire("o"):
                await asyncio.sleep(0.01)

        await asyncio.gather(hold(), hold())  # contended acquire binds the semaphore

    # An APP-scoped runtime outliving asyncio.run() is endorsed usage; the
    # second loop must get fresh, unbound semaphores.
    asyncio.run(contended_use())
    asyncio.run(contended_use())


def test__limit__enforced_within_one_loop() -> None:
    limiter = AsyncOriginLimiter(limit=1)
    peak = 0
    active = 0

    async def task() -> None:
        nonlocal peak, active
        async with limiter.acquire("o"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    async def main() -> None:
        await asyncio.gather(*(task() for _ in range(4)))

    asyncio.run(main())
    assert peak == 1


def test__parallel_loops_in_threads__each_get_their_own_limit() -> None:
    limiter = AsyncOriginLimiter(limit=1)
    errors: list[BaseException] = []

    def worker() -> None:
        async def use() -> None:
            async with limiter.acquire("o"):
                await asyncio.sleep(0.01)

        try:
            asyncio.run(use())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


# --- sync limiter ---


def test__limit__enforced_across_threads() -> None:
    limiter = SyncOriginLimiter(limit=1)
    peak = 0
    active = 0
    lock = threading.Lock()

    def task() -> None:
        nonlocal peak, active
        with limiter.acquire("o"):
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1

    threads = [threading.Thread(target=task) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 1
