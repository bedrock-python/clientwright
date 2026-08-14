"""Property invariants of the pure retry policy, driven by hypothesis."""
# ruff: noqa: S311 - seeded Random drives deterministic jitter, not cryptography

from __future__ import annotations

from random import Random

from hypothesis import given
from hypothesis import strategies as st

from clientwright.core.config import RetryConfig
from clientwright.core.model import Attempt, FailureKind, Outcome, RequestInfo
from clientwright.core.policy.retry import DefaultRetryPolicy

INFO_GET = RequestInfo(method="GET", origin="https://a:443", url="https://a/u")
INFO_POST = RequestInfo(method="POST", origin="https://a:443", url="https://a/u", idempotent=False)

positive_floats = st.floats(min_value=0.001, max_value=30.0, allow_nan=False, allow_infinity=False)

retry_configs = st.builds(
    RetryConfig,
    max_attempts=st.integers(min_value=1, max_value=8),
    initial_backoff=positive_floats,
    max_backoff=positive_floats,
    multiplier=st.floats(min_value=1.0, max_value=4.0, allow_nan=False),
    jitter=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    respect_retry_after=st.booleans(),
    retry_after_max=positive_floats,
)

failing_outcomes = st.one_of(
    st.builds(
        Outcome,
        kind=st.sampled_from(sorted(FailureKind, key=str)),
        retry_after=st.none() | st.floats(min_value=0.0, max_value=120.0, allow_nan=False),
    ),
    st.builds(
        Outcome,
        kind=st.just(FailureKind.STATUS),
        status_code=st.integers(min_value=500, max_value=599),
    ),
    st.builds(Outcome, kind=st.none(), status_code=st.integers(min_value=200, max_value=499)),
)


def _history(outcome: Outcome, length: int) -> list[Attempt]:
    return [Attempt(index=i, started=0.0, duration=0.01, outcome=outcome) for i in range(1, length + 1)]


@given(
    config=retry_configs, outcome=failing_outcomes, length=st.integers(min_value=1, max_value=10), seed=st.integers()
)
def test__delay__never_negative_and_bounded(config: RetryConfig, outcome: Outcome, length: int, seed: int) -> None:
    policy = DefaultRetryPolicy(config)
    decision = policy.decide(
        info=INFO_GET, history=_history(outcome, length), remaining=None, replayable=True, rng=Random(seed)
    )
    assert decision.delay >= 0.0
    if decision.retry:
        ceiling = max(config.max_backoff * (1.0 + config.jitter), config.retry_after_max)
        assert decision.delay <= ceiling + 1e-9


@given(config=retry_configs, outcome=failing_outcomes, extra=st.integers(min_value=0, max_value=5), seed=st.integers())
def test__attempts__never_exceed_max(config: RetryConfig, outcome: Outcome, extra: int, seed: int) -> None:
    policy = DefaultRetryPolicy(config)
    decision = policy.decide(
        info=INFO_GET,
        history=_history(outcome, config.max_attempts + extra),
        remaining=None,
        replayable=True,
        rng=Random(seed),
    )
    assert not decision.retry


@given(
    config=retry_configs,
    outcome=failing_outcomes,
    remaining=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    seed=st.integers(),
)
def test__deadline__backoff_never_lands_past_the_remaining_budget(
    config: RetryConfig, outcome: Outcome, remaining: float, seed: int
) -> None:
    policy = DefaultRetryPolicy(config)
    decision = policy.decide(
        info=INFO_GET, history=_history(outcome, 1), remaining=remaining, replayable=True, rng=Random(seed)
    )
    if decision.retry:
        assert decision.delay + 0.001 < remaining + 1e-9


@given(config=retry_configs, status=st.integers(min_value=200, max_value=299), seed=st.integers())
def test__success__is_always_final(config: RetryConfig, status: int, seed: int) -> None:
    policy = DefaultRetryPolicy(config)
    decision = policy.decide(
        info=INFO_GET,
        history=_history(Outcome(kind=None, status_code=status), 1),
        remaining=None,
        replayable=True,
        rng=Random(seed),
    )
    assert not decision.retry


@given(config=retry_configs, outcome=failing_outcomes, seed=st.integers())
def test__non_idempotent_post__never_retried(config: RetryConfig, outcome: Outcome, seed: int) -> None:
    policy = DefaultRetryPolicy(config)
    decision = policy.decide(
        info=INFO_POST, history=_history(outcome, 1), remaining=None, replayable=True, rng=Random(seed)
    )
    assert not decision.retry


@given(config=retry_configs, outcome=failing_outcomes, seed=st.integers())
def test__same_seed__same_decision(config: RetryConfig, outcome: Outcome, seed: int) -> None:
    policy = DefaultRetryPolicy(config)

    def run() -> tuple[bool, float, str]:
        decision = policy.decide(
            info=INFO_GET, history=_history(outcome, 1), remaining=None, replayable=True, rng=Random(seed)
        )
        return decision.retry, decision.delay, decision.reason

    assert run() == run()
