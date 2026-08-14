"""Property invariants of the capability algebra."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from clientwright.core.capabilities import AdapterCapabilities, DurationBoundary, SeamGranularity, dead_retryable_kinds
from clientwright.core.model import FailureKind

kinds = st.sets(st.sampled_from(sorted(FailureKind, key=str)), max_size=len(FailureKind)).map(frozenset)
collapse_maps = st.dictionaries(
    st.sampled_from(sorted(FailureKind, key=str)),
    st.sampled_from(sorted(FailureKind, key=str)),
    max_size=6,
)


def _capabilities(emits: frozenset[FailureKind], collapses: dict[FailureKind, FailureKind]) -> AdapterCapabilities:
    return AdapterCapabilities(
        adapter="prop",
        seam="test",
        granularity=SeamGranularity.LOGICAL,
        boundary=DurationBoundary.HEADERS,
        support={},
        emits=emits,
        collapses=collapses,
    )


@given(requested=kinds, emits=kinds, collapses=collapse_maps)
def test__dead_kinds__subset_of_requested_and_disjoint_from_reachable(
    requested: frozenset[FailureKind], emits: frozenset[FailureKind], collapses: dict[FailureKind, FailureKind]
) -> None:
    dead = dead_retryable_kinds(requested, _capabilities(emits, collapses))
    assert dead <= requested
    assert not (dead & emits)
    for source, target in collapses.items():
        if target in emits:
            assert source not in dead  # collapsed kinds are reachable through their target


@given(requested=kinds, emits=kinds)
def test__without_collapses__dead_is_exactly_the_set_difference(
    requested: frozenset[FailureKind], emits: frozenset[FailureKind]
) -> None:
    dead = dead_retryable_kinds(requested, _capabilities(emits, {}))
    assert dead == requested - emits
