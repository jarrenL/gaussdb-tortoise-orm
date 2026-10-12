"""GaussDB O-mode compatibility contracts.

Values in this module are NOT guesses: each contract is pinned by a probe
script (scripts/probe_*.py) executed against the two real 507 instances, and
every constant carries a pointer to the probe that pinned it. If a probe
result changes against a different 507 build, the contract and the related
tests must be re-run before shipping.

O-mode identity:
- Centralized 507  : pg_database.datcompatibility = 'A'
- Distributed 507  : pg_database.datcompatibility = 'ORA'
The plan requires we read the full value and never guess by first letter or
port number, and refuse to run against PG/M/B modes.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Mode identity
# ---------------------------------------------------------------------------

#: datcompatibility values accepted as "Oracle-compatible" per the plan.
#: Centralized reports 'A', distributed reports 'ORA' (verified on both
#: live instances via probe_mode.py, 2026-10-08, see reports/).
O_MODE_VALUES = frozenset({"A", "ORA"})

#: Values we explicitly refuse to run against (plan §5.1).
KNOWN_NON_O_VALUES = frozenset({"PG", "B", "MYSQL", "M"})

# Semantic contracts pinned by probe_o_semantics.py / type_bisect.py /
# ts_vs_date_probe.py / drop_semantics.py / dist_evidence.py (2026-10-08,
# both shapes). See docs/o_mode_contracts.md for full transcripts.

#: '' (empty string) is stored/returned as NULL in O mode on 507 (both shapes).
#: NOT NULL columns therefore reject '' with NotNullViolation.
O_MODE_EMPTY_STRING_IS_NULL = True

#: CHAR values keep trailing spaces on round-trip in O mode.
O_MODE_CHAR_PRESERVES_TRAILING_SPACES = True

#: DATE columns arrive with wire OID 1116 (timestamp's oid) and text
#: 'YYYY-MM-DD 00:00:00 AD' — the era suffix discriminates them from true
#: timestamps (oid 1114, no suffix). Requires the GaussDBDateBinaryDumper
#: (8-byte micros) + era-aware loaders in wire_adapters.py.
O_MODE_DATE_WIRE_IS_TIMESTAMP_OID = 1116

#: ISO date literals are rejected in O mode ('invalid value for "MON"');
#: 'DD-MON-YYYY' parses DAY-FIRST ('29-JAN-2024' == 2024-01-29!).
#: to_date(s, 'YYYY-MM-DD') is the safe parse path.
O_MODE_DATE_LITERAL_IS_ORACLE_STYLE = True

#: Distributed CN: unqualified DDL/DML does not honour search_path (INSERT
#: fails with "does not exist on DN ..."). All identifiers must be
#: schema-qualified (Tortoise Meta.schema).
DIST_CN_REQUIRES_SCHEMA_QUALIFICATION = True

#: Distributed CN: physical REFERENCES constraints are not supported at all
#: (FeatureNotSupported). ORM relations must use db_constraint=False.
DIST_CN_NO_PHYSICAL_FK = True

#: Distributed: unique indexes NOT containing the distribution key are
#: rejected ("cannot be enforced to remote nodes"). Business unique keys
#: must include the distribution column.
DIST_UNIQUE_MUST_CONTAIN_DISTRIBUTE_KEY = True


class GaussDBModeError(Exception):
    """Raised when the target database is not a 507 O-mode GaussDB instance.

    Carries the observed datcompatibility value so the failure is diagnosable
    without leaking credentials.
    """
