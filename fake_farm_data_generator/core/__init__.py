# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency-free helpers shared by plugin algorithms."""

from .generation import (
    FAKE_WARNING,
    VARIABILITY_MULTIPLIERS,
    deterministic_operation_date,
    idw_value,
    parse_years,
    stable_seed,
)

__all__ = [
    "FAKE_WARNING",
    "VARIABILITY_MULTIPLIERS",
    "deterministic_operation_date",
    "idw_value",
    "parse_years",
    "stable_seed",
]
