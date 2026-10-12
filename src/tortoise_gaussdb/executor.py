"""GaussDB executor: parameter style + insert-result handling.

Self-contained: extends BasePostgresExecutor directly (the upstream psycopg
executor is a thin wrapper identical to this one, but importing it would drag
in the ``psycopg`` package, which is not installable alongside the gaussdb
fork — see client.py).
"""

from __future__ import annotations

from pypika_tortoise import Parameter

from tortoise import Model
from tortoise.backends.base_postgres.executor import BasePostgresExecutor


class GaussDBExecutor(BasePostgresExecutor):
    """The gaussdb driver shares psycopg's %s placeholder and dict-row
    insert-result processing, so behaviour is inherited. Kept as a separate
    class so GaussDB-specific overrides have a home."""

    async def _process_insert_result(
        self, instance: Model, results: dict | None
    ) -> None:
        if results:
            db_projection = instance._meta.fields_db_projection_reverse
            for key, val in results.items():
                if key in db_projection:
                    model_field = db_projection[key]
                    field_object = self.model._meta.fields_map[model_field]
                    setattr(instance, model_field, field_object.to_python_value(val))

    def _prepare_insert_statement(self, columns, has_generated=True, ignore_conflicts=False):
        query = super()._prepare_insert_statement(columns, has_generated, ignore_conflicts)
        query._gaussdb_projection = self.model._meta.fields_db_projection.copy()
        # Bulk create does not backfill generated IDs in upstream Tortoise.
        query._gaussdb_bulk_template = True
        return query

    def parameter(self, pos: int) -> Parameter:
        return Parameter("%s")
