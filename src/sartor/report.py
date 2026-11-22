"""Coverage and gap report (S-008).

Per requirement: evidenced (with its bullet), weak, or gap — plus the
ATS keyword table. Gaps are only ever phrased as "add evidence or
accept the gap".
"""

from __future__ import annotations

from pathlib import Path


class ReportError(Exception):
    """Raised when the report cannot be built."""


def build_report(project: Path, target: str) -> Path:
    """Write ``exports/<target>/report.md`` and ``coverage.json``."""
    raise NotImplementedError("S-008: report")
