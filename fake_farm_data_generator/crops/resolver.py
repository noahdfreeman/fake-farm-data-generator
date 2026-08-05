# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve CDL class histograms into reviewable field-year assignments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Mapping, Optional

from .cdl_classes import (
    AGRICULTURAL_CODES,
    DOUBLE_CROP_CODES,
    class_name,
    profile_for_code,
)


@dataclass(frozen=True)
class CropAssignment:
    crop_name: Optional[str]
    crop_code: Optional[int]
    crop_pct: float
    crop_source: str
    crop_source_year: int
    crop_resolution: Optional[float]
    crop_lookup_at: str
    crop_overridden: bool
    cdl_class_name: Optional[str]
    status: str
    review_required: bool
    valid_agricultural_pixels: int
    total_pixels: int

    def to_dict(self):
        return asdict(self)


def classify_histogram(
    histogram: Mapping[int, int],
    source: str,
    year: int,
    resolution: Optional[float] = None,
    threshold: float = 0.40,
    lookup_at: Optional[str] = None,
) -> CropAssignment:
    """Classify the dominant agricultural CDL class.

    Percent dominance is calculated only from valid agricultural pixels.  The
    assignment is auto-accepted at or above the configured threshold only when
    the class maps unambiguously to a supported v1 crop profile.
    """

    cleaned = {
        int(code): max(0, int(count))
        for code, count in histogram.items()
        if int(count) > 0
    }
    total_pixels = sum(cleaned.values())
    agricultural = {
        code: count for code, count in cleaned.items() if code in AGRICULTURAL_CODES
    }
    agricultural_total = sum(agricultural.values())
    timestamp = lookup_at or datetime.now().astimezone().isoformat(timespec="seconds")
    if agricultural_total <= 0:
        return CropAssignment(
            crop_name=None,
            crop_code=None,
            crop_pct=0.0,
            crop_source=source,
            crop_source_year=int(year),
            crop_resolution=resolution,
            crop_lookup_at=timestamp,
            crop_overridden=False,
            cdl_class_name=None,
            status="no_agricultural_pixels",
            review_required=True,
            valid_agricultural_pixels=0,
            total_pixels=total_pixels,
        )

    code, count = max(agricultural.items(), key=lambda item: (item[1], -item[0]))
    fraction = count / agricultural_total
    profile = profile_for_code(code)
    if code in DOUBLE_CROP_CODES:
        status = "mapping_required"
        review_required = True
    elif profile is None:
        status = "unsupported_class"
        review_required = True
    elif fraction < float(threshold):
        status = "below_threshold"
        review_required = True
    else:
        status = "accepted"
        review_required = False
    return CropAssignment(
        crop_name=profile,
        crop_code=code,
        crop_pct=round(fraction * 100.0, 3),
        crop_source=source,
        crop_source_year=int(year),
        crop_resolution=resolution,
        crop_lookup_at=timestamp,
        crop_overridden=False,
        cdl_class_name=class_name(code),
        status=status,
        review_required=review_required,
        valid_agricultural_pixels=agricultural_total,
        total_pixels=total_pixels,
    )


def apply_manual_override(
    assignment: Optional[CropAssignment],
    crop_name: str,
    year: int,
    lookup_at: Optional[str] = None,
) -> CropAssignment:
    """Return a reviewed manual assignment while retaining available provenance."""

    timestamp = lookup_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return CropAssignment(
        crop_name=str(crop_name),
        crop_code=assignment.crop_code if assignment else None,
        crop_pct=assignment.crop_pct if assignment else 0.0,
        crop_source="manual",
        crop_source_year=assignment.crop_source_year if assignment else int(year),
        crop_resolution=assignment.crop_resolution if assignment else None,
        crop_lookup_at=assignment.crop_lookup_at if assignment else timestamp,
        crop_overridden=assignment is not None,
        cdl_class_name=assignment.cdl_class_name if assignment else None,
        status="manual",
        review_required=False,
        valid_agricultural_pixels=(assignment.valid_agricultural_pixels if assignment else 0),
        total_pixels=assignment.total_pixels if assignment else 0,
    )
