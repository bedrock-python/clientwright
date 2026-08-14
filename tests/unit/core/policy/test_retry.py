"""Pure retry policy decisions."""

from __future__ import annotations

from random import Random

from clientwright.core.config import RetryConfig
from clientwright.core.model import Attempt, FailureKind, Outcome, RequestInfo
from clientwright.core.policy.retry import DefaultRetryPolicy

INFO_GET = RequestInfo(method="GET", origin="https://a:443", url="https://a/u")
INFO_POST = RequestInfo(method="POST", origin="https://a:443", url="https://a/u", idempotent=False)
INFO_POST_IDEMPOTENT = RequestInfo(method="POST", origin="https://a:443", url="https://a/u", idempotent=True)


def attempt(outcome: Outcome, index: int = 1) -> Attempt:
    return Attempt(index=index, started=0.0, duration=0.01, outcome=outcome)


def history(*outcomes: Outcome) -> list[Attempt]:
    return [attempt(outcome, index) for index, outcome in enumerate(outcomes, start=1)]


def decide(policy: DefaultRetryPolicy, hist: list[Attempt], info: RequestInfo = INFO_GET, **kwargs: object):
    defaults: dict[str, object] = {"remaining": None, "replayable": True, "rng": Random(1)}  # noqa: S311
    defaults.update(kwargs)
    return policy.decide(info=info, history=hist, **defaults)  # type: ignore[arg-type]


def test__empty_history__no_attempts_reason() -> None:
    policy = DefaultRetryPolicy(RetryConfig())
    decision = decide(policy, [])
    assert not decision.retry
    assert decision.reason == "no_attempts"


def test__success_response__final() -> None:
    policy = DefaultRetryPolicy(RetryConfig())
    decision = decide(policy, history(Outcome(kind=None, status_code=200)))
    assert not decision.retry
    assert decision.reason == "final"


def test__retryable_status__retries_with_backoff() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0, initial_backoff=0.5))
    decision = decide(policy, history(Outcome(kind=FailureKind.STATUS, status_code=503)))
    assert decision.retry
    assert decision.reason == "status_503"
    assert decision.delay == 0.5


def test__retryable_kind__retries() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0))
    decision = decide(policy, history(Outcome(kind=FailureKind.READ_TIMEOUT)))
    assert decision.retry
    assert decision.reason == "kind_read_timeout"


def test__non_retryable_500__final() -> None:
    policy = DefaultRetryPolicy(RetryConfig())
    decision = decide(policy, history(Outcome(kind=FailureKind.STATUS, status_code=500)))
    assert not decision.retry


def test__attempts_exhausted__stops() -> None:
    policy = DefaultRetryPolicy(RetryConfig(max_attempts=2))
    failing = Outcome(kind=FailureKind.STATUS, status_code=503)
    decision = decide(policy, history(failing, failing))
    assert not decision.retry
    assert decision.reason == "attempts"


def test__post_without_idempotency__denied_by_method() -> None:
    policy = DefaultRetryPolicy(RetryConfig())
    decision = decide(policy, history(Outcome(kind=FailureKind.CONNECT_TIMEOUT)), info=INFO_POST)
    assert not decision.retry
    assert decision.reason == "method"


def test__post_with_idempotency_flag__allowed() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0))
    decision = decide(policy, history(Outcome(kind=FailureKind.CONNECT_TIMEOUT)), info=INFO_POST_IDEMPOTENT)
    assert decision.retry


def test__non_replayable_body__denied() -> None:
    policy = DefaultRetryPolicy(RetryConfig())
    decision = decide(policy, history(Outcome(kind=FailureKind.READ_TIMEOUT)), replayable=False)
    assert not decision.retry
    assert decision.reason == "non_replayable"


def test__deadline_too_close_for_backoff__denied() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0, initial_backoff=1.0))
    decision = decide(policy, history(Outcome(kind=FailureKind.READ_TIMEOUT)), remaining=0.5)
    assert not decision.retry
    assert decision.reason == "deadline"


def test__retry_after__respected_and_capped() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0, retry_after_max=10.0))
    decision = decide(policy, history(Outcome(kind=FailureKind.STATUS, status_code=429, retry_after=3.0)))
    assert decision.retry
    assert decision.delay == 3.0
    capped = decide(policy, history(Outcome(kind=FailureKind.STATUS, status_code=429, retry_after=600.0)))
    assert capped.delay == 10.0


def test__jitter__spreads_delay_within_the_configured_band() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.2, initial_backoff=1.0))
    failing = Outcome(kind=FailureKind.READ_TIMEOUT)
    delays = {decide(policy, history(failing), rng=Random(seed)).delay for seed in range(20)}  # noqa: S311
    assert all(0.8 <= delay <= 1.2 for delay in delays)
    assert len(delays) > 1  # jitter actually varies the delay


def test__backoff__exponential_and_capped() -> None:
    policy = DefaultRetryPolicy(RetryConfig(jitter=0.0, initial_backoff=1.0, multiplier=2.0, max_backoff=3.0))
    failing = Outcome(kind=FailureKind.READ_TIMEOUT)
    assert decide(policy, history(failing), remaining=None).delay == 1.0
    assert decide(policy, history(failing, failing), remaining=None).delay == 2.0
    third = decide(policy, history(failing, failing, failing), remaining=None)
    assert not third.retry  # max_attempts default 3
    wide = DefaultRetryPolicy(
        RetryConfig(max_attempts=5, jitter=0.0, initial_backoff=1.0, multiplier=2.0, max_backoff=3.0)
    )
    assert decide(wide, history(failing, failing, failing), remaining=None).delay == 3.0
