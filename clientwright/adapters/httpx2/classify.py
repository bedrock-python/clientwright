"""httpx2 exception -> FailureKind classification (shared family logic)."""

from __future__ import annotations

from ...core.model import FailureKind
from .._httpx_shared import classify_family_error
from ._imports import httpx2


def classify_error(exc: BaseException) -> FailureKind:
    return classify_family_error(httpx2, exc)


__all__ = ["classify_error"]
