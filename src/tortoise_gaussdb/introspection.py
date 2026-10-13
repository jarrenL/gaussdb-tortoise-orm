"""Catalog inspection for an existing GaussDB schema (read only)."""

from tortoise_gaussdb.schema import quote_identifier


async def inspect_schema(client, schema: str):
    quote_identifier(schema)  # Validate the public API, bind all catalog filters.
    relations = await client.execute_query_dict(
        "SELECT c.relname AS name, c.relkind AS kind FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind IN ('r','v','m','S') ORDER BY c.relname",
        [schema],
    )
    columns = await client.execute_query_dict(
        "SELECT c.relname AS table_name,a.attname AS name,a.attnum AS position, "
        "format_type(a.atttypid,a.atttypmod) AS data_type,NOT a.attnotnull AS nullable, "
        "pg_get_expr(d.adbin,d.adrelid) AS default_expression, "
        "col_description(c.oid,a.attnum) AS comment "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname=%s AND c.relkind IN ('r','v','m') "
        "AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum",
        [schema],
    )
    constraints = await client.execute_query_dict(
        "SELECT c.relname AS table_name,k.conname AS name,k.contype AS kind, "
        "pg_get_constraintdef(k.oid) AS definition "
        "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s ORDER BY c.relname,k.conname",
        [schema],
    )
    indexes = await client.execute_query_dict(
        "SELECT c.relname AS table_name,i.relname AS name,x.indisunique AS is_unique, "
        "x.indisprimary AS is_primary,pg_get_indexdef(i.oid) AS definition "
        "FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid "
        "JOIN pg_class i ON i.oid=x.indexrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s ORDER BY c.relname,i.relname",
        [schema],
    )
    layouts = []
    if client.deployment == "distributed":
        layouts = await client.execute_query_dict(
            "SELECT c.relname AS table_name,x.pclocatortype AS locator, "
            "a.attname AS distribution_column FROM pgxc_class x "
            "JOIN pg_class c ON c.oid=x.pcrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(x.pcattnum) "
            "WHERE n.nspname=%s ORDER BY c.relname",
            [schema],
        )
    return {
        "schema": schema,
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "distribution": layouts,
    }
