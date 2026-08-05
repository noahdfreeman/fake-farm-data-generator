# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable-review size settings shared by Processing and the custom dialog."""

from __future__ import annotations


DEFAULT_REVIEW_MAX_FEATURES = 20_000
MIN_REVIEW_MAX_FEATURES = 100
MAX_REVIEW_MAX_FEATURES = 200_000


def normalize_review_max_features(value):
    """Return a bounded whole-number per-layer browser feature limit."""

    if isinstance(value, bool):
        raise ValueError("review_max_features must be a whole number")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("review_max_features must be a whole number") from error
    if not numeric.is_integer():
        raise ValueError("review_max_features must be a whole number")
    result = int(numeric)
    if not MIN_REVIEW_MAX_FEATURES <= result <= MAX_REVIEW_MAX_FEATURES:
        raise ValueError(
            f"review_max_features must be between {MIN_REVIEW_MAX_FEATURES:,} "
            f"and {MAX_REVIEW_MAX_FEATURES:,}"
        )
    return result
