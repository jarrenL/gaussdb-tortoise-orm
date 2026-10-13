"""GaussDB executor: parameter style + insert-result handling.

Self-contained: extends BasePostgresExecutor directly (the upstream psycopg
executor is a thin wrapper identical to this one, but importing it would drag
in the ``psycopg`` package, which is not installable alongside the gaussdb
fork — see client.py).
"""

from __future__ import annotations

from pypika_tortoise import Parameter

from tortoise import Model
from tortoise.filters import json_filter
from tortoise_gaussdb.json_functions import json_filter as gaussdb_json_filter
from tortoise.backends.base_postgres.executor import BasePostgresExecutor


class GaussDBExecutor(BasePostgresExecutor):
    """The gaussdb driver shares psycopg's %s placeholder and dict-row
    insert-result processing, so behaviour is inherited. Kept as a separate
    class so GaussDB-specific overrides have a home."""

    FILTER_FUNC_OVERRIDE = {
        **BasePostgresExecutor.FILTER_FUNC_OVERRIDE,
        json_filter: gaussdb_json_filter,
    }

    async def execute_explain(self, sql, output_fmt=None, **options):
        from tortoise.exceptions import UnSupportedError

        # The centralized 507 build emits malformed JSON in EXPLAIN FORMAT JSON.
        # TEXT is verified on both layouts; do not advertise PostgreSQL formats.
        if output_fmt and output_fmt.upper() != "TEXT":
            raise UnSupportedError("GaussDB EXPLAIN currently supports TEXT only")
        supported = {"analyze", "verbose", "costs", "buffers", "timing"}
        if set(options) - supported:
            raise UnSupportedError("Unsupported GaussDB EXPLAIN option")
        return await super().execute_explain(sql, output_fmt="TEXT", **options)

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

    def _prepare_insert_statement(
        self, columns, has_generated=True, ignore_conflicts=False
    ):
        query = super()._prepare_insert_statement(
            columns, has_generated, ignore_conflicts
        )
        query._gaussdb_projection = self.model._meta.fields_db_projection.copy()
        # Bulk create does not backfill generated IDs in upstream Tortoise.
        query._gaussdb_bulk_template = True
        return query

    def parameter(self, pos: int) -> Parameter:
        return Parameter("%s")
