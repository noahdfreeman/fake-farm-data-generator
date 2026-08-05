# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistent elapsed-time and remaining-time feedback for long QGIS runs."""

from __future__ import annotations

import time


def format_duration(seconds):
    """Return a compact human-readable duration without external dependencies."""

    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


class ProgressReporter:
    """Report progress, elapsed time, records, and a simple remaining estimate."""

    def __init__(
        self,
        feedback,
        total_units,
        label,
        *,
        clock=time.monotonic,
        minimum_message_interval=5.0,
    ):
        self.feedback = feedback
        self.total_units = max(1, int(total_units))
        self.label = str(label)
        self.clock = clock
        self.minimum_message_interval = max(0.0, float(minimum_message_interval))
        self.started_at = self.clock()
        self.last_message_at = self.started_at
        self.last_completed = 0

    def update(self, completed_units, stage, records=None, *, force=False):
        completed = min(self.total_units, max(0, int(completed_units)))
        self.last_completed = max(self.last_completed, completed)
        percent = int(self.last_completed / self.total_units * 100)
        if self.feedback is not None:
            self.feedback.setProgress(percent)

        now = self.clock()
        elapsed = max(0.0, now - self.started_at)
        should_message = (
            force
            or self.last_completed >= self.total_units
            or now - self.last_message_at >= self.minimum_message_interval
        )
        if not should_message or self.feedback is None:
            return

        if self.last_completed > 0 and self.last_completed < self.total_units:
            remaining = elapsed * (
                (self.total_units - self.last_completed) / self.last_completed
            )
            remaining_text = format_duration(remaining)
        elif self.last_completed >= self.total_units:
            remaining_text = "0s"
        else:
            remaining_text = "calculating"
        record_text = ""
        if records is not None:
            record_text = f"; {int(records):,} records created"
        self.feedback.pushInfo(
            f"{self.label}: {stage}; {percent}%{record_text}; "
            f"elapsed {format_duration(elapsed)}; estimated remaining {remaining_text}"
        )
        self.last_message_at = now
