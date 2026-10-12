"""GaussDB 507 schema generation, shared with the migration editor."""

from tortoise.backends.base_postgres.schema_generator import BasePostgresSchemaGenerator
from tortoise.exceptions import ConfigurationError
from tortoise_gaussdb.distributed import (
    DistributionError,
    distribution_sql,
    validate_distribution,
)


def quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ConfigurationError("Identifiers must be nonempty and contain no NUL")
    return '"' + value.replace('"', '""') + '"'


def create_schema_sql(schema: str, safe: bool = True) -> str:
    ddl = f"CREATE SCHEMA {quote_identifier(schema)}"
    if not safe:
        return ddl + ";"
    # Offline SQL and generate_schemas use the same server-side path.
    # Only duplicate_schema is suppressed, never permission errors.
    literal = "E'" + ddl.replace("\\", "\\\\").replace("'", "''") + "'"
    body = f"BEGIN EXECUTE {literal}; EXCEPTION WHEN duplicate_schema THEN NULL; END"
    tag = "$gaussdb_schema$"
    while tag in body:
        tag = tag[:-1] + "_$"
    return f"DO {tag}{body}{tag};"


class DistributionMixin:
    """Physical schema/table/column names work for historical models too."""

    def quote(self, value):
        return quote_identifier(value)

    def _distribution_for(self, table, schema, columns, unique_sets=()):
        client = self.client
        key = f"{schema or 'public'}.{table}"
        config = client.distributions.get(key)
        if client.deployment == "centralized":
            return ""
        if client.deployment != "distributed":
            raise ConfigurationError(
                "Set credentials.deployment to centralized or distributed"
            )
        if not schema:
            raise DistributionError(
                f"{key}: distributed models require explicit Meta.schema"
            )
        dist = validate_distribution({"distribution": config})
        if not dist:
            if client.allow_default_distribution:
                return ""
            raise DistributionError(f"Missing credentials.distributions[{key!r}]")
        if dist["type"] == "HASH":
            field = dist["field"]
            if field not in columns:
                raise DistributionError(
                    f"{key}: unknown physical distribution column {field!r}"
                )
            for unique in unique_sets:
                if field not in unique:
                    raise DistributionError(
                        f"{key}: unique key {unique} must include {field!r} on 507"
                    )
            return " " + distribution_sql(dist, self.quote(field))
        return " " + distribution_sql(dist)

    def _check_model(self, model):
        for column in model._meta.fields_db_projection.values():
            # Upstream interpolates field names inside quote characters.
            if '"' in column or "\x00" in column:
                raise ConfigurationError(
                    "Embedded quotes/NUL in column names are not supported"
                )
        if self.client.deployment == "distributed":
            for field in model._meta.fields_map.values():
                reference = getattr(field, "reference", None)
                if reference and reference.db_constraint:
                    raise DistributionError(
                        "507 distributed physical FK requires explicit db_constraint=False"
                    )
            for name in model._meta.m2m_fields:
                field = model._meta.fields_map[name]
                if not field._generated and field.db_constraint:
                    raise DistributionError(
                        "507 distributed M2M requires explicit db_constraint=False"
                    )

    def _model_distribution(self, model):
        self._check_model(model)
        unique_sets = [(model._meta.db_pk_column,)]
        for name, column in model._meta.fields_db_projection.items():
            if model._meta.fields_map[name].unique:
                unique_sets.append((column,))
        for fields in model._meta.unique_together:
            unique_sets.append(
                tuple(model._meta.fields_map[f].source_field or f for f in fields)
            )
        return self._distribution_for(
            model._meta.db_table,
            model._meta.schema,
            model._meta.fields_db_projection.values(),
            unique_sets,
        )


class GaussDBSchemaGenerator(DistributionMixin, BasePostgresSchemaGenerator):
    def _get_schema_create_sql(self, schema, safe):
        return create_schema_sql(schema, safe)

    async def probe_existing_schemas(self):
        """Compatibility no-op: standard generation no longer needs a probe."""

    def _get_table_sql(self, model, safe=True):
        self._active_model = model
        self._active_distribution = self._model_distribution(model)
        try:
            return super()._get_table_sql(model, safe)
        finally:
            self._active_model = None

    def _table_generate_extra(self, table):
        model = self._active_model
        if table == model._meta.db_table:
            return self._active_distribution
        for name in model._meta.m2m_fields:
            field = model._meta.fields_map[name]
            if field.through == table:
                columns = (field.backward_key, field.forward_key)
                return self._distribution_for(
                    table,
                    model._meta.schema,
                    columns,
                    [columns] if field.unique else [],
                )
        raise DistributionError(f"Unknown generated table {table}")
