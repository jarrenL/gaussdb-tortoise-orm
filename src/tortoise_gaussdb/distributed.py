"""Validated HASH/REPLICATION layouts keyed by physical schema.table.

Configure credentials.distributions; Meta.distribution is not retained by
Tortoise historical model serialization and is intentionally not an API.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_DISTRIBUTION_TYPES = frozenset({"HASH", "REPLICATION"})


class DistributionError(Exception):
    """Raised when a model's distribution configuration is invalid."""


def validate_distribution(meta_dict: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a Meta['distribution'] dict. Returns it normalized, or None
    when absent. Raises DistributionError on invalid input."""
    dist = meta_dict.get("distribution")
    if dist is None:
        return None
    if not isinstance(dist, dict):
        raise DistributionError(
            "Meta.distribution must be a dict like "
            "{'type': 'HASH', 'field': 'id'} or {'type': 'REPLICATION'}"
        )
    dtype = str(dist.get("type", "")).upper()
    if dtype not in SUPPORTED_DISTRIBUTION_TYPES:
        raise DistributionError(
            f"Unsupported distribution type {dtype!r}; supported: "
            f"{sorted(SUPPORTED_DISTRIBUTION_TYPES)} (probed on 507; "
            "extend SUPPORTED_DISTRIBUTION_TYPES only with probe evidence)"
        )
    if dtype == "HASH" and (
        not isinstance(dist.get("field"), str) or not dist["field"]
    ):
        raise DistributionError("HASH distribution requires a 'field'")
    normalized = {"type": dtype}
    if dtype == "HASH":
        normalized["field"] = dist["field"]
    return normalized


def distribution_sql(dist: dict[str, Any] | None, quoted_field: str = "") -> str:
    """Render the DISTRIBUTE BY clause (no leading space). Empty string when
    dist is None."""
    if not dist:
        return ""
    if dist["type"] == "HASH":
        return f"DISTRIBUTE BY HASH({quoted_field})"
    return f"DISTRIBUTE BY {dist['type']}"
