"""GaussDB async client for Tortoise-ORM (self-contained, no psycopg import).

Layering (plan §3): this module re-implements the upstream psycopg backend's
client contract but imports ONLY the gaussdb driver (gaussdb / gaussdb_pool).
The upstream tortoise.backends.psycopg module hard-imports the ``psycopg``
package at module level, which is not installable alongside the gaussdb fork
in this project's environments; re-implementing the ~250-line client keeps the
adapter dependency-clean and GaussDB-specific behaviour explicit.

Key GaussDB specifics handled here:
- driver/pool: gaussdb / gaussdb_pool (psycopg3-fork, %s placeholders)
- O-mode preflight on first connect (datcompatibility in {A, ORA}, plan §5.1)
- wire-format dumper registration per pooled connection (plan W07: date)
- exception translation using gaussdb's error classes
"""

from __future__ import annotations

import asyncio
import re
from ssl import SSLContext
from typing import Any, Callable, TypeVar

import gaussdb
import gaussdb.conninfo
import gaussdb.pq
import gaussdb.rows
import gaussdb_pool
from pypika_tortoise import SqlContext
from pypika_tortoise.dialects.postgresql import PostgreSQLQuery, PostgreSQLQueryBuilder
from pypika_tortoise.terms import Parameterizer

import tortoise.backends.base.client as base_client
import tortoise.backends.base_postgres.client as postgres_client
import tortoise.exceptions as exceptions
from tortoise_gaussdb import wire_adapters
from tortoise_gaussdb.capabilities import gaussdb_capabilities
from tortoise_gaussdb.contracts import O_MODE_VALUES
from tortoise_gaussdb.executor import GaussDBExecutor
from tortoise_gaussdb.schema import GaussDBSchemaGenerator, quote_identifier
from tortoise_gaussdb.upsert import annotated_sql, split_contract, validate_target

FuncType = Callable[..., Any]
F = TypeVar("F", bound=FuncType)


def translate_exceptions(func: F) -> F:
    # reuse the base_postgres wrapper shape but with our own _translate_exceptions
    async def _translate_exceptions(self, *args, **kwargs):
        return await self._translate_exceptions(func, *args, **kwargs)

    return _translate_exceptions  # type: ignore[return-value]


class GaussDBPool(gaussdb_pool.AsyncConnectionPool):
    """gaussdb_pool async pool with the acquire/release aliasing Tortoise
    expects."""

    async def acquire(self, *args, **kwargs) -> gaussdb.AsyncConnection:
        return await self.getconn(*args, **kwargs)

    async def release(self, connection: gaussdb.AsyncConnection) -> None:
        await self.putconn(connection)


class GaussDBSQLQuery(PostgreSQLQuery):
    @classmethod
    def _builder(cls, **kwargs) -> "GaussDBSQLQueryBuilder":
        return GaussDBSQLQueryBuilder(**kwargs)


class GaussDBSQLQueryBuilder(PostgreSQLQueryBuilder):
    """gaussdb uses the same %s parameter placeholder as psycopg."""

    def get_parameterized_sql(self, ctx: SqlContext | None = None) -> tuple[str, list]:
        if not ctx:
            ctx = self.QUERY_CLS.SQL_CONTEXT
        if not ctx.parameterizer:
            ctx = ctx.copy(
                parameterizer=Parameterizer(placeholder_factory=lambda _: "%s")
            )
        return super().get_parameterized_sql(ctx)

    def _on_conflict_sql(self, ctx):
        if (
            self._on_conflict_fields
            or self._on_conflict_do_updates
            or self._on_conflict_wheres
        ):
            raise exceptions.OperationalError(
                "507 supports ignore_conflicts only; targeted on_conflict/update_fields is not supported"
            )
        if not self._on_conflict_do_nothing:
            raise exceptions.OperationalError("Incomplete conflict action")
        return " ON DUPLICATE KEY UPDATE NOTHING"

    def _on_conflict_action_sql(self, ctx):
        return ""

    def get_sql(self, ctx=None):
        if not self._on_conflict_fields:
            return super().get_sql(ctx)
        ctx = ctx or self.QUERY_CLS.SQL_CONTEXT
        if (self._on_conflict_wheres or self._on_conflict_do_update_wheres or
                self._selects or self._with or not self._values):
            raise exceptions.OperationalError("Targeted upsert requires VALUES without conditions/CTEs")
        if self._returns and not self.__dict__.get("_gaussdb_bulk_template",False):
            raise exceptions.OperationalError("MERGE RETURNING is not supported")
        projection = self.__dict__.get("_gaussdb_projection",{})
        columns = [field.name for field in self._columns]
        keys = [projection.get(field.name,field.name) for field in self._on_conflict_fields]
        if not keys or len(set(keys))!=len(keys) or not set(keys)<=set(columns):
            raise exceptions.OperationalError("Conflict keys must be distinct inserted columns")
        updates = []
        for field,value in self._on_conflict_do_updates:
            name = projection.get(field.name,field.name)
            if value is not None or name not in columns or name in keys:
                raise exceptions.OperationalError("Updates must copy inserted non-key columns")
            updates.append(name)
        if not updates and not self._on_conflict_do_nothing:
            raise exceptions.OperationalError("Incomplete conflict action")
        table = self._insert_table._table_name
        schema = self._insert_table._schema
        if schema is not None and schema._parent is not None:
            raise exceptions.OperationalError("Cross-database MERGE is not supported")
        schema = schema._name if schema is not None else None
        target = (quote_identifier(schema)+"." if schema else "")+quote_identifier(table)
        names = [quote_identifier(name) for name in columns]
        # A zero-row typed projection preserves actual column types, including
        # NULL/Decimal/DATE, without guessing parameter casts from Python data.
        source = "SELECT "+",".join(names)+" FROM "+target+" WHERE 1=0"
        for row in self._values:
            if len(row)!=len(columns):
                raise exceptions.OperationalError("Insert column/value count mismatch")
            source += " UNION ALL SELECT "+",".join(value.get_sql(ctx) for value in row)+" FROM dual"
        sql = "MERGE INTO "+target+" t USING ("+source+") s ON "+" AND ".join(
            "t."+quote_identifier(key)+"=s."+quote_identifier(key) for key in keys
        )
        if updates:
            sql += " WHEN MATCHED THEN UPDATE SET "+",".join(
                quote_identifier(name)+"=s."+quote_identifier(name) for name in updates
            )
        sql += " WHEN NOT MATCHED THEN INSERT ("+",".join(names)+") VALUES ("+",".join("s."+name for name in names)+")"
        return annotated_sql({"schema":schema,"table":table,"keys":keys},sql)


class GaussDBClient(postgres_client.BasePostgresClient):
    query_class: type[GaussDBSQLQuery] = GaussDBSQLQuery
    executor_class: type[GaussDBExecutor] = GaussDBExecutor
    schema_generator: type[GaussDBSchemaGenerator] = GaussDBSchemaGenerator
    capabilities = gaussdb_capabilities
    _pool: GaussDBPool | None = None
    _connection: gaussdb.AsyncConnection | None = None
    default_timeout: float = 30

    def __init__(self, **kwargs: Any) -> None:
        # W04: optional preflight toggles/extra config
        self.deployment = kwargs.pop("deployment", None)
        if self.deployment not in (None, "centralized", "distributed"):
            raise exceptions.ConfigurationError(
                "Invalid deployment: use centralized or distributed"
            )
        self.distributions = kwargs.pop("distributions", {}).copy()
        self.allow_default_distribution = kwargs.pop(
            "allow_default_distribution", False
        )
        if not isinstance(self.allow_default_distribution, bool):
            raise exceptions.ConfigurationError(
                "allow_default_distribution must be boolean"
            )
        self._skip_mode_check = kwargs.pop("skip_mode_check", False)
        if not isinstance(self._skip_mode_check, bool):
            raise exceptions.ConfigurationError("skip_mode_check must be boolean")
        self._mode_checked: bool = False
        super().__init__(**kwargs)

    # -- connection ---------------------------------------------------------

    async def create_connection(self, with_db: bool) -> None:
        if self._pool is not None:
            raise RuntimeError("Connection pool already created")

        self.server_settings["application_name"] = self.application_name

        extra = self.extra.copy()
        extra.setdefault("timeout", self.default_timeout)
        ssl: SSLContext | None = extra.pop("ssl", None)
        if isinstance(ssl, SSLContext):
            raise exceptions.ConfigurationError(
                "Use server_settings sslmode/sslrootcert/sslcert/sslkey for libpq TLS; "
                "an SSLContext cannot be transferred to libpq"
            )
        if ssl:
            if isinstance(ssl, SSLContext) and ssl.check_hostname:
                self.server_settings["sslmode"] = "verify-full"
            else:
                self.server_settings["sslmode"] = "require"

        conninfo = gaussdb.conninfo.make_conninfo(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database if with_db else None,
            **self.server_settings,
        )

        self._template = {
            "conninfo": conninfo,
            "min_size": self.pool_minsize,
            "max_size": self.pool_maxsize,
            "kwargs": {
                "autocommit": True,
                "row_factory": gaussdb.rows.dict_row,
            },
            "connection_class": gaussdb.AsyncConnection,
            # every new pooled connection gets the GaussDB wire-format
            # dumper fixes (date -> int64 micros) registered automatically;
            # note: async because the fork's pool awaits configure callbacks
            "configure": self._configure_connection,
            **extra,
        }

        try:
            self._pool = await self.create_pool(**self._template)
            await self._pool.open(wait=True, timeout=extra["timeout"])
            await self._post_connect()
            if not self._skip_mode_check and not self._mode_checked:
                await self._preflight_mode_check()
            self.log.debug("Created GaussDB connection pool")
        except BaseException as exc:
            await self._close()
            if isinstance(exc, (gaussdb.OperationalError, gaussdb_pool.PoolTimeout)):
                raise exceptions.DBConnectionError(
                    "Cannot establish GaussDB connection"
                ) from exc
            raise

    async def _configure_connection(self, conn):
        await wire_adapters.aregister(conn)
        if self.schema:
            from tortoise_gaussdb.schema import quote_identifier

            await conn.execute(
                "SELECT set_config('search_path', %s, false)",
                [quote_identifier(self.schema)],
            )

    async def _preflight_mode_check(self) -> None:
        """W04/ENV-02: verify the target is really a 507 O-mode GaussDB.

        Reads the full datcompatibility value — never guesses by first letter
        or port. Refuses to run on non-O values (PG/M/B/MYSQL).
        """
        _, rows = await self.execute_query(
            "SELECT current_database() AS db, "
            "pg_database.datcompatibility AS compat, "
            "version() AS version "
            "FROM pg_database WHERE datname = current_database()"
        )
        if not rows:
            raise exceptions.DBConnectionError("Mode preflight returned no rows")
        compat = rows[0]["compat"]
        if not re.search(r"GaussDB.*\b507(?:\.|\b)", rows[0]["version"], re.I):
            raise exceptions.DBConnectionError("Expected GaussDB kernel 507")
        if compat not in O_MODE_VALUES:
            raise exceptions.DBConnectionError(
                f"tortoise_gaussdb requires GaussDB 507 O-mode (datcompatibility in "
                f"{sorted(O_MODE_VALUES)}), got {compat!r} on database {rows[0]['db']!r}. "
                f"Refusing to run against a non-O database."
            )
        self._mode_checked = True
        self.log.info(
            "GaussDB O-mode preflight OK: db=%s compat=%s version=%s",
            rows[0]["db"],
            compat,
            rows[0]["version"],
        )

    async def create_pool(self, **kwargs) -> GaussDBPool:
        pool = GaussDBPool(open=False, **kwargs)
        await pool.open()
        return pool

    async def db_delete(self) -> None:
        try:
            return await super().db_delete()
        except gaussdb.errors.InvalidCatalogName:  # pragma: nocoverage
            pass

    # -- execution ----------------------------------------------------------

    async def execute_insert(self, query: str, values: list) -> Any | None:
        inserted, rows = await self.execute_query(query, values)
        if rows:
            return rows[0]
        return None

    @translate_exceptions
    async def execute_many(self, query: str, values: list) -> None:
        connection: gaussdb.AsyncConnection
        async with self.acquire_connection() as connection:
            meta, query = split_contract(query)
            if meta:
                async with connection.transaction():
                    await validate_target(connection,meta,self.schema)
                    async with connection.cursor() as cursor:
                        await cursor.executemany(query,values)
                return
            async with connection.cursor() as cursor:
                self.log.debug("Execute batch (%s parameter sets)", len(values))
                await cursor.executemany(query, values)

    @translate_exceptions
    async def execute_query(
        self,
        query: str,
        values: list | None = None,
        row_factory=gaussdb.rows.dict_row,
    ) -> tuple[int, list[dict]]:
        connection: gaussdb.AsyncConnection
        async with self.acquire_connection() as connection:
            meta, query = split_contract(query)
            if meta:
                await validate_target(connection,meta,self.schema)
            cursor: gaussdb.AsyncCursor | gaussdb.AsyncServerCursor
            async with connection.cursor(row_factory=row_factory) as cursor:
                self.log.debug("Execute query (%s parameters)", len(values or []))
                await cursor.execute(query, values)

                rowcount = int(cursor.rowcount or cursor.rownumber or 0)

                if (
                    cursor.pgresult
                    and cursor.pgresult.status == gaussdb.pq.ExecStatus.TUPLES_OK
                ):
                    rows = await cursor.fetchall()
                else:
                    rows = []

                return rowcount, rows

    async def execute_query_dict(
        self, query: str, values: list | None = None
    ) -> list[dict]:
        rowcount, rows = await self.execute_query(
            query, values, row_factory=gaussdb.rows.dict_row
        )
        return rows

    # -- lifecycle ----------------------------------------------------------

    async def _expire_connections(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = await self.create_pool(**self._template)

    async def _close(self) -> None:
        if self._pool:
            pool = self._pool
            self._pool = None
            await pool.close(10)
            self._mode_checked = False
            self.log.debug("Closed connection pool %s", pool)

    async def _translate_exceptions(self, func, *args, **kwargs) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except (
            gaussdb.errors.SyntaxErrorOrAccessRuleViolation,
            gaussdb.errors.DataException,
            gaussdb.errors.UndefinedTable,
        ) as exc:
            raise exceptions.OperationalError(exc)
        except gaussdb.errors.IntegrityError as exc:
            raise exceptions.IntegrityError(exc)
        except (
            gaussdb.errors.InvalidTransactionState,
            gaussdb.errors.InFailedSqlTransaction,
        ) as exc:
            raise exceptions.TransactionManagementError(exc)

    def _in_transaction(self) -> base_client.TransactionContext:
        return base_client.TransactionContextPooled(
            TransactionWrapper(self), self._pool_init_lock
        )


class TransactionWrapper(GaussDBClient, base_client.TransactionalDBClient):
    """Transactional wrapper; gaussdb (like psycopg) implements nested
    transactions (savepoints) natively."""

    _connection: gaussdb.AsyncConnection

    def __init__(self, connection: GaussDBClient) -> None:
        self._connection: gaussdb.AsyncConnection = connection._connection
        self._lock = asyncio.Lock()
        self.log = connection.log
        self.connection_name = connection.connection_name
        self._transaction = None
        self._finalized = False
        self._parent = connection
        self.deployment = connection.deployment
        self.distributions = connection.distributions
        self.allow_default_distribution = connection.allow_default_distribution
        self.schema = connection.schema

    def _in_transaction(self) -> base_client.TransactionContext:
        return base_client.NestedTransactionContext(TransactionWrapper(self))

    def acquire_connection(
        self,
    ) -> base_client.ConnectionWrapper[gaussdb.AsyncConnection]:
        return base_client.ConnectionWrapper(self._lock, self)

    @translate_exceptions
    async def begin(self) -> None:
        self._transaction = self._connection.transaction()
        await self._transaction.__aenter__()

    async def savepoint(self) -> None:
        return await self.begin()

    async def commit(self) -> None:
        if not self._transaction:
            raise exceptions.TransactionManagementError(
                "Transaction is in invalid state"
            )
        if self._finalized:
            raise exceptions.TransactionManagementError("Transaction already finalised")
        await self._transaction.__aexit__(None, None, None)
        self._finalized = True

    async def release_savepoint(self) -> None:
        await self.commit()

    async def rollback(self) -> None:
        if not self._transaction:
            raise exceptions.TransactionManagementError(
                "Transaction is in invalid state"
            )
        if self._finalized:
            raise exceptions.TransactionManagementError("Transaction already finalised")
        await self._transaction.__aexit__(gaussdb.Rollback, gaussdb.Rollback(), None)
        self._finalized = True

    async def savepoint_rollback(self) -> None:
        await self.rollback()
