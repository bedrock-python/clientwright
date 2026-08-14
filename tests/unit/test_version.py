"""Tests for the package metadata."""

from __future__ import annotations

import pytest

import clientwright

pytestmark = pytest.mark.unit


def test__package__imported__exposes_non_empty_version() -> None:
    # Act
    version = clientwright.__version__

    # Assert
    assert isinstance(version, str)
    assert version
