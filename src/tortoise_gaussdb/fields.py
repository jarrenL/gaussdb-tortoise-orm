"""Optional fields with portable O-mode representations."""

import json
from tortoise import fields


class JSONField(fields.JSONField):
    """Serialize Unicode literally for O-mode databases using SQL_ASCII too.

    JSON escaped Unicode above U+007F is rejected by GaussDB JSONB in that
    encoding. Python values and serialized JSON strings share this path.
    """

    def to_db_value(self, value, instance):
        serialized = super().to_db_value(value, instance)
        if serialized is None:
            return None
        return json.dumps(
            json.loads(serialized), ensure_ascii=False, separators=(",", ":")
        )


class DurationField(fields.TimeDeltaField):
    """Timedelta stored as integer microseconds, using Tortoise's portable field."""
