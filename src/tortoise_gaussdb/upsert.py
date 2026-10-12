"""Exact-target MERGE contract, validated against live unique indexes."""
import base64
import json
from tortoise.exceptions import OperationalError

PREFIX = "/*gaussdb-target:"


def annotated_sql(meta, sql):
    token = base64.urlsafe_b64encode(json.dumps(meta).encode()).decode()
    return PREFIX + token + "*/ " + sql


def split_contract(sql):
    if not sql.startswith(PREFIX):
        return None, sql
    header, tail = sql[len(PREFIX):].split("*/ ", 1)
    try:
        meta = json.loads(base64.urlsafe_b64decode(header).decode())
        if (not isinstance(meta.get("table"), str) or not meta["table"] or
                not meta.get("keys") or not all(isinstance(k,str) for k in meta["keys"])):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as error:
        raise OperationalError("Invalid targeted upsert contract") from error
    return meta, tail


async def validate_target(connection, meta, default_schema):
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT idx.relname,att.attname FROM pg_index ix "
            "JOIN pg_class rel ON rel.oid=ix.indrelid "
            "JOIN pg_namespace n ON n.oid=rel.relnamespace "
            "JOIN pg_class idx ON idx.oid=ix.indexrelid "
            "JOIN pg_attribute att ON att.attrelid=rel.oid AND att.attnum=ANY(ix.indkey) "
            "WHERE n.nspname=%s AND rel.relname=%s AND ix.indisunique "
            "AND ix.indpred IS NULL AND ix.indexprs IS NULL",
            [meta.get("schema") or default_schema or "public",meta["table"]],
        )
        rows = await cursor.fetchall()
    groups = {}
    for row in rows:
        name, field = (row["relname"],row["attname"]) if isinstance(row,dict) else row
        groups.setdefault(name,set()).add(field)
    keys = meta["keys"]
    if len(keys)!=len(set(keys)) or not any(fields==set(keys) for fields in groups.values()):
        raise OperationalError("on_conflict must match an existing unconditional unique index")
