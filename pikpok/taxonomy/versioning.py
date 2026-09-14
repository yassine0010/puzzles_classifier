"""Taxonomy versioning utilities.

Taxonomy versions follow semantic versioning (MAJOR.MINOR.PATCH).
Canonical IDs must remain stable after release — only display names may change
in patch bumps.  Structural changes (new/removed IDs) require a minor bump.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True)
class TaxonomyVersion:
    """A parsed semantic version for the taxonomy."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, version_str: str) -> TaxonomyVersion:
        m = _VERSION_RE.match(version_str.strip())
        if m is None:
            raise ValueError(
                f"Invalid taxonomy version string: '{version_str}'"
            )
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def versions_compatible(
    record_version: str, current_version: str
) -> bool:
    """Check if a record's taxonomy version is compatible with the current one.

    Compatible means same major version.  Records from a different major
    version should be re-evaluated.
    """
    rv = TaxonomyVersion.parse(record_version)
    cv = TaxonomyVersion.parse(current_version)
    return rv.major == cv.major
