"""Extended O-mode contracts, executed independently on both deployments."""

import asyncio
import datetime as dt
import decimal
import os
import uuid
from copy import deepcopy

import pytest
import pytest_asyncio
from tortoise import Tortoise, fields
from tortoise.contrib.postgres.fields import ArrayField
from tortoise.expressions import F, Q, Case, When, Subquery
from tortoise.functions import Count, Sum, Avg, Min, Max
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError, OperationalError, ConfigurationError
from tortoise_gaussdb.models import GaussDBModel
from tortoise_gaussdb.fields import JSONField, DurationField
from tortoise_gaussdb.client import GaussDBClient

SCHEMA = "extended_" + uuid.uuid4().hex[:10]


class DataRow(GaussDBModel):
    id = fields.IntField(primary_key=True, generated=False)
    name = fields.CharField(max_length=80, null=True)
    small = fields.SmallIntField(null=True)
    big = fields.BigIntField(null=True)
    real = fields.FloatField(null=True)
    flag = fields.BooleanField(null=True)
    uid = fields.UUIDField(null=True)
    stamp = fields.DatetimeField(null=True)
    clock = fields.TimeField(null=True)
    born = fields.DateField(null=True)
    data = JSONField(null=True)
    duration = DurationField(null=True)
    numbers = ArrayField(null=True)
    amount = fields.DecimalField(max_digits=18, decimal_places=4, null=True)

    class Meta:
        table = "data_rows"
        schema = SCHEMA


@pytest_asyncio.fixture(params=["CENTRAL", "DIST"])
async def db(request):
    tag = request.param
    credentials = {
        "host": os.getenv("TEST_HOST", "host.docker.internal"),
        "port": os.environ[tag + "_PORT"],
        "database": os.environ[tag + "_DB"],
        "user": os.environ[tag + "_USER"],
        "password": os.environ.get(tag + "_PASSWORD", os.environ["CENTRAL_PASSWORD"]),
        "deployment": "distributed" if tag == "DIST" else "centralized",
        "schema": SCHEMA,
        "minsize": 1,
        "maxsize": 3,
        "timeout": 3,
        "distributions": {f"{SCHEMA}.data_rows": {"type": "HASH", "field": "id"}},
    }
    config = {
        "connections": {
            "default": {"engine": "tortoise_gaussdb", "credentials": credentials}
        },
        "apps": {"models": {"models": [__name__]}},
        "use_tz": True,
        "timezone": "UTC",
    }
    await Tortoise.init(config=config)
    conn = Tortoise.get_connection("default")
    conn.test_credentials = credentials
    try:
        await Tortoise.generate_schemas()
        yield conn
    finally:
        await conn.execute_script(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "small,big,flag",
    [
        (-32768, -9223372036854775808, False),
        (32767, 9223372036854775807, True),
        (None, None, None),
    ],
)
async def test_types_bounds(db, small, big, flag):
    uid = uuid.uuid4()
    stamp = dt.datetime(
        2024, 2, 29, 12, 34, 56, 123456, tzinfo=dt.timezone(dt.timedelta(hours=8))
    )
    row = await DataRow.create(
        id=1,
        small=small,
        big=big,
        flag=flag,
        real=-1.25,
        uid=uid,
        stamp=stamp,
        born=dt.date(2024, 2, 29),
        clock=dt.time(12, 34, 56, 123456, tzinfo=dt.timezone.utc),
        amount=decimal.Decimal("-1234.5678"),
        name="中文'\\%_😀",
    )
    await row.refresh_from_db()
    assert (row.small, row.big, row.flag, row.uid) == (small, big, flag, uid)
    assert row.stamp == stamp and row.clock == dt.time(
        12, 34, 56, 123456, tzinfo=dt.timezone.utc
    )
    assert row.born == dt.date(2024, 2, 29) and row.real == -1.25
    assert row.amount == decimal.Decimal("-1234.5678") and row.name == "中文'\\%_😀"


@pytest.mark.parametrize(
    "data",
    [
        {"a": {"n": 3}, "tags": ["x", "y"], "null": None},
        [1, "中文", None],
        42,
        False,
        "null",
        None,
    ],
)
async def test_json_roundtrip(db, data):
    await DataRow.create(id=1, data=data)
    assert (await DataRow.get(id=1)).data == (None if data == "null" else data)


async def test_json_filters(db):
    await DataRow.create(id=1, data={"a": {"n": 3}, "tags": ["x", "y"]})
    await DataRow.create(id=2, data={"a": {"n": 9}})
    assert await DataRow.filter(data__contains={"a": {"n": 3}}).count() == 1
    assert await DataRow.filter(data__filter={"a__n__gte": 5}).values_list(
        "id", flat=True
    ) == [2]
    assert await DataRow.filter(data__filter={"tags__0": "x"}).count() == 1


async def test_arrays(db):
    await DataRow.create(id=1, numbers=[1, 2, 3])
    await DataRow.create(id=2, numbers=[])
    assert (await DataRow.get(id=1)).numbers == [1, 2, 3]
    assert (await DataRow.get(id=2)).numbers == []
    assert await DataRow.filter(numbers__contains=[2]).count() == 1
    assert await DataRow.filter(numbers__overlap=[3, 9]).count() == 1
    assert await DataRow.filter(numbers__len=3).count() == 1


async def test_stream_and_inspect(db):
    await DataRow.bulk_create([DataRow(id=i, name=f"row{i}") for i in range(25)])
    sql = f'SELECT id,name FROM "{SCHEMA}".data_rows WHERE id >= %s ORDER BY id'
    async with db.stream_query(sql, [3], batch_size=4) as stream:
        assert [r["id"] async for r in stream] == list(range(3, 25))
    async with db.stream_query(sql, [0], batch_size=2) as stream:
        async for row in stream:
            assert row["id"] == 0
            break
    assert await DataRow.all().count() == 25
    async with in_transaction() as tx:
        async with tx.stream_query(sql, [24], batch_size=2) as stream:
            assert [r["id"] async for r in stream] == [24]
    meta = await db.inspect_schema()
    assert any(c["name"] == "id" and not c["nullable"] for c in meta["columns"])
    assert any(c["kind"] == "p" for c in meta["constraints"])
    if db.deployment == "distributed":
        assert any(d["distribution_column"] == "id" for d in meta["distribution"])
    assert (await db.inspect_schema("absent_'schema"))["relations"] == []


async def test_queries(db):
    await DataRow.bulk_create(
        [DataRow(id=i, small=i % 2, big=i, name=f"n{i}") for i in range(6)]
    )
    assert await DataRow.filter(~Q(id__in=[1, 3, 5])).order_by("id").offset(1).limit(
        2
    ).values_list("id", flat=True) == [2, 4]
    assert (
        await DataRow.filter(
            id__in=Subquery(DataRow.filter(id__gte=4).values("id"))
        ).count()
        == 2
    )
    rows = (
        await DataRow.annotate(
            n=Count("id"), s=Sum("big"), a=Avg("big"), lo=Min("big"), hi=Max("big")
        )
        .group_by("small")
        .filter(n__gte=3)
        .order_by("small")
        .values("small", "n", "s", "a", "lo", "hi")
    )
    assert [r["s"] for r in rows] == [6, 9]
    assert (
        await DataRow.annotate(label=Case(When(id__gte=4, then=1), default=0))
        .filter(label=1)
        .count()
        == 2
    )
    assert await DataRow.all().distinct().count() == 6


async def test_transaction_isolation_and_cancel(db):
    await DataRow.create(id=1, big=1)
    credentials = {**db.test_credentials, "isolation_level": "REPEATABLE READ"}
    observer = GaussDBClient(connection_name="observer", **credentials)
    try:
        await observer.create_connection(True)
        async with observer.acquire_connection() as raw:
            async with raw.transaction():
                assert (
                    await (await raw.execute("SHOW transaction_isolation")).fetchone()
                )["transaction_isolation"] == "repeatable read"
                sql = f'SELECT big FROM "{SCHEMA}".data_rows WHERE id=1'
                assert (await (await raw.execute(sql)).fetchone())["big"] == 1
                await DataRow.filter(id=1).update(big=2)
                assert (await (await raw.execute(sql)).fetchone())["big"] == 1
    finally:
        await observer.close()
    ready = asyncio.Event()

    async def worker():
        async with in_transaction():
            await DataRow.create(id=2)
            ready.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(worker())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await DataRow.filter(id=2).exists()
    assert await DataRow.all().count() == 1


async def test_bulk_failure_atomicity(db):
    await DataRow.create(id=3)
    with pytest.raises(IntegrityError):
        async with in_transaction():
            await DataRow.bulk_create(
                [DataRow(id=i) for i in [1, 2, 3, 4]], batch_size=2
            )
    assert await DataRow.all().values_list("id", flat=True) == [3]


async def test_lock_options(db):
    await DataRow.create(id=1)
    async with in_transaction():
        rows = await DataRow.filter(id=1).select_for_update(nowait=True)
        assert len(rows) == 1
    async with in_transaction():
        rows = await DataRow.filter(id=1).select_for_update(skip_locked=True)
        assert len(rows) == 1
    async with in_transaction():
        rows = await DataRow.filter(id=1).select_for_update().limit(1)
        assert len(rows) == 1


async def test_datetime_window_and_duration(db):
    from tortoise_gaussdb.functions import Extract, DateTrunc, Window

    start = dt.datetime(2024, 2, 29, 20, 30, tzinfo=dt.timezone.utc)
    await DataRow.bulk_create(
        [
            DataRow(
                id=i,
                small=i % 2,
                big=i,
                stamp=start,
                duration=dt.timedelta(days=-1, microseconds=123456),
            )
            for i in range(1, 7)
        ]
    )
    rows = (
        await DataRow.annotate(
            h=Extract("stamp", "hour", "Asia/Shanghai"),
            day=DateTrunc("stamp", "day", "Asia/Shanghai"),
        )
        .order_by("id")
        .values("h", "day")
    )
    assert rows[0]["h"] == 4 and rows[0]["day"].day == 1
    assert (await DataRow.get(id=1)).duration == dt.timedelta(
        days=-1, microseconds=123456
    )
    rows = (
        await DataRow.annotate(
            rn=Window("row_number", partition_by=("small",), order_by=("id",)),
            running=Window("sum", "big", order_by=("id",), rows=(None, 0)),
        )
        .order_by("id")
        .values("rn", "running")
    )
    assert [r["rn"] for r in rows] == [1, 1, 2, 2, 3, 3]
    assert [r["running"] for r in rows] == [1, 3, 6, 10, 15, 21]
    assert await DataRow.filter(stamp__year=2024).count() == 6


async def test_json_paths_and_unicode(db):
    await DataRow.create(id=1, data={"嵌套": {"v": 3}, "a": None, "bad'key": "值😀"})
    row = await DataRow.get(id=1)
    assert row.data["bad'key"] == "值😀"
    assert await DataRow.filter(data__filter={"bad'key": "值😀"}).count() == 1
    assert await DataRow.filter(data__filter={"嵌套__v": 3}).count() == 1
    assert await DataRow.filter(data__filter={"a__isnull": True}).count() == 1
    await DataRow.create(id=2, data='{"a":"\\u4e2d\\u6587"}')
    assert (await DataRow.get(id=2)).data == {"a": "中文"}


async def test_stream_cancellation_error_and_pool_reuse(db):
    sql = f'SELECT id FROM "{SCHEMA}".data_rows ORDER BY id'
    await DataRow.bulk_create([DataRow(id=i) for i in range(5)])
    ready = asyncio.Event()

    async def worker():
        async with db.stream_query(sql, batch_size=1) as rows:
            async for row in rows:
                ready.set()
                await asyncio.sleep(60)

    task = asyncio.create_task(worker())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Repeated early exits exceed pool capacity; leaked connections would time out.
    for _ in range(5):
        async with db.stream_query(sql, batch_size=1) as rows:
            assert (await anext(rows))["id"] == 0
    with pytest.raises(ConfigurationError):
        async with db.stream_query(sql, batch_size=0):
            pass
    assert await DataRow.all().count() == 5


async def test_concurrent_transactions_and_unique_creation(db):
    ready = [asyncio.Event(), asyncio.Event()]

    async def worker(i, rollback):
        try:
            async with in_transaction():
                await DataRow.create(id=i)
                ready[i - 1].set()
                await ready[2 - i].wait()
                assert await DataRow.filter(id=i).exists()
                assert not await DataRow.filter(id=3 - i).exists()
                if rollback:
                    raise ValueError("rollback one only")
        except ValueError:
            if not rollback:
                raise

    await asyncio.gather(worker(1, False), worker(2, True))
    assert await DataRow.all().values_list("id", flat=True) == [1]
    results = await asyncio.gather(
        *(DataRow.get_or_create(id=7, defaults={"name": "same"}) for _ in range(8))
    )
    assert sum(created for _, created in results) == 1
    assert {row.id for row, _ in results} == {7}
    row, created = await DataRow.update_or_create(id=7, defaults={"name": "updated"})
    assert not created and row.name == "updated"


async def test_lock_contention_and_of(db):
    import gaussdb

    await DataRow.create(id=1)
    await DataRow.create(id=2)
    async with in_transaction():
        await DataRow.filter(id=1).select_for_update(of=("data_rows",))
        async with db.acquire_connection() as raw:
            async with raw.transaction():
                result = await raw.execute(
                    f'SELECT id FROM "{SCHEMA}".data_rows ORDER BY id FOR UPDATE SKIP LOCKED'
                )
                assert [r["id"] for r in await result.fetchall()] == [2]
            with pytest.raises(gaussdb.errors.LockNotAvailable):
                async with raw.transaction():
                    await raw.execute(
                        f'SELECT id FROM "{SCHEMA}".data_rows WHERE id=1 FOR UPDATE NOWAIT'
                    )
    with pytest.raises(ConfigurationError):
        await DataRow.all().select_for_update(nowait=True, skip_locked=True)


async def test_migration_field_defaults_null_type_constraints(db):
    from copy import copy
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor
    from tortoise.migrations.constraints import UniqueConstraint

    editor = GaussDBSchemaEditor(db, atomic=False)
    await DataRow.create(id=1, name="keep")
    old = DataRow._meta.fields_map["name"]
    new = deepcopy(old)
    new.max_length = 120
    new.null = False
    new.db_default = "default"
    new.description = "中文注释'100%"

    # The public alter_field API consumes historical models. Provide a metadata
    # snapshot representing the new state without mutating the live model.
    class NewState:
        pass

    NewState._meta = copy(DataRow._meta)
    NewState._meta.fields_map = {**DataRow._meta.fields_map, "name": new}
    await editor.alter_field(DataRow, NewState, "name")
    columns = (await db.inspect_schema())["columns"]
    name = next(x for x in columns if x["name"] == "name")
    assert (
        not name["nullable"]
        and "120" in name["data_type"]
        and name["comment"] == "中文注释'100%"
    )
    await db.execute_query(f'INSERT INTO "{SCHEMA}".data_rows (id) VALUES (%s)', [2])
    assert (await DataRow.get(id=2)).name == "default"
    constraint = UniqueConstraint(fields=("id", "name"), name="custom_unique")
    await editor.add_constraint(DataRow, constraint)
    assert any(
        c["name"] == "custom_unique" for c in (await db.inspect_schema())["constraints"]
    )
    await editor.remove_constraint(DataRow, constraint)
    await editor.alter_field(NewState, DataRow, "name")
    await DataRow.create(id=3, name=None)
    assert (await DataRow.get(id=1)).name == "keep"


@pytest.mark.parametrize("level", ["READ COMMITTED", "REPEATABLE READ"])
async def test_isolation_configuration(db, level):
    client = GaussDBClient(
        connection_name="isolation", **{**db.test_credentials, "isolation_level": level}
    )
    try:
        await client.create_connection(True)
        async with client.acquire_connection() as raw:
            async with raw.transaction():
                result = await (
                    await raw.execute("SHOW transaction_isolation")
                ).fetchone()
                assert result["transaction_isolation"] == level.lower()
    finally:
        await client.close()


async def test_error_translation_and_recovery(db):
    with pytest.raises(OperationalError):
        await db.execute_query("SELECT nonexistent_function_507()")
    with pytest.raises(OperationalError):
        await db.execute_query("SELECT CAST('bad' AS integer)")
    with pytest.raises(IntegrityError):
        await db.execute_query(f'INSERT INTO "{SCHEMA}".data_rows(id) VALUES (NULL)')
    await DataRow.create(id=1)
    assert await DataRow.all().count() == 1


async def test_multi_alias_independent_rollback(db):
    from tortoise import connections

    connection_config = {
        "engine": "tortoise_gaussdb",
        "credentials": db.test_credentials,
    }
    # Use Tortoise's public connection handler; transactions must bind by alias.
    await connections._init({"secondary": connection_config}, create_db=False)
    try:
        async with in_transaction("default"):
            await DataRow.create(id=1)
            try:
                async with in_transaction("secondary") as second:
                    await DataRow.create(id=2, using_db=second)
                    raise ValueError("secondary rollback")
            except ValueError:
                pass
    finally:
        await connections.get("secondary").close()
        connections.discard("secondary")
    assert await DataRow.all().values_list("id", flat=True) == [1]


@pytest.mark.parametrize("on_delete", ["CASCADE", "RESTRICT", "SET NULL"])
async def test_physical_foreign_keys(db, on_delete):
    import types
    from tortoise import Model
    from tortoise_gaussdb.schema import GaussDBSchemaGenerator
    from tortoise_gaussdb.distributed import DistributionError

    module = types.ModuleType("physical_models")

    class Parent(Model):
        id = fields.IntField(primary_key=True, generated=False)

        class Meta:
            table = "physical_parent"
            schema = SCHEMA

    class Dependent(Model):
        id = fields.IntField(primary_key=True, generated=False)
        parent = fields.ForeignKeyField(
            "physical.Parent", on_delete=on_delete, null=True, db_constraint=True
        )

        class Meta:
            table = "physical_child"
            schema = SCHEMA

    module.Parent, module.Dependent = Parent, Dependent
    Tortoise.init_models([module], "physical")
    Parent._meta.default_connection = Dependent._meta.default_connection = "default"
    Tortoise._build_initial_querysets()
    db.distributions.update(
        {
            f"{SCHEMA}.{name}": {"type": "HASH", "field": "id"}
            for name in ["physical_parent", "physical_child"]
        }
    )
    generator = GaussDBSchemaGenerator(db)
    if db.deployment == "distributed":
        with pytest.raises(DistributionError, match="physical FK"):
            generator._get_table_sql(Dependent, False)
        return
    for model in [Parent, Dependent]:
        data = generator._get_table_sql(model, False)
        await db.execute_script(data["table_creation_string"])
    parent = await Parent.create(id=1)
    await Dependent.create(id=1, parent=parent)
    with pytest.raises(IntegrityError):
        await Dependent.create(id=2, parent_id=999)
    if on_delete == "RESTRICT":
        with pytest.raises(IntegrityError):
            await parent.delete()
        assert await Dependent.all().count() == 1
    else:
        await parent.delete()
        if on_delete == "CASCADE":
            assert await Dependent.all().count() == 0
        else:
            assert (await Dependent.get(id=1)).parent_id is None


async def test_combined_rename_and_alter(db):
    from copy import copy
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor

    editor = GaussDBSchemaEditor(db, atomic=False)
    await DataRow.create(id=1, name="keep")
    old = DataRow._meta.fields_map["name"]
    new = deepcopy(old)
    new.source_field = "renamed_name"
    new.max_length = 100
    new.null = False

    class NewState:
        pass

    NewState._meta = copy(DataRow._meta)
    NewState._meta.fields_map = {**DataRow._meta.fields_map, "name": new}
    await editor.alter_field(DataRow, NewState, "name")
    row = (
        await db.execute_query_dict(f'SELECT renamed_name FROM "{SCHEMA}".data_rows')
    )[0]
    assert row["renamed_name"] == "keep"
    await editor.alter_field(NewState, DataRow, "name")
    assert (await DataRow.get(id=1)).name == "keep"


async def test_explain_and_lookups(db):
    from tortoise.functions import Upper, Lower, Length

    await DataRow.create(id=1, name="Ab_%\\c", big=5)
    await DataRow.create(id=2, name=None)
    assert await DataRow.filter(name__contains="_%").count() == 1
    assert await DataRow.filter(name__iexact="ab_%\\c").count() == 1
    assert await DataRow.filter(name__startswith="Ab_").count() == 1
    rows = (
        await DataRow.filter(id=1)
        .annotate(u=Upper("name"), l=Lower("name"), n=Length("name"))
        .values("u", "l", "n")
    )
    assert rows == [{"u": "AB_%\\C", "l": "ab_%\\c", "n": 6}]
    assert await DataRow.all().explain()
    assert await DataRow.all().explain(output_fmt="TEXT")


async def test_json_projection_and_build(db):
    from tortoise_gaussdb.functions import JSONExtract, JSONObject, JSONF

    await DataRow.create(id=1, data={"bad'key": {"n": 3}})
    rows = await DataRow.annotate(
        n=JSONExtract("data", "bad'key", "n"), j=JSONObject(number=F("id"), constant=7)
    ).values("n", "j")
    assert rows == [{"n": "3", "j": {"number": 1, "constant": 7}}]
    assert await DataRow.annotate(n=JSONF("data__bad'key__n")).values_list(
        "n", flat=True
    ) == ["3"]
    assert await DataRow.annotate(
        n=JSONExtract("data", "bad'key", text=False)
    ).values_list("n", flat=True) == [{"n": 3}]
    assert await DataRow.annotate(
        j=JSONObject(**{"中文'key": [1, None, True]})
    ).values_list("j", flat=True) == [{"中文'key": [1, None, True]}]


async def test_window_functions_frames_and_duration_arithmetic(db):
    from tortoise_gaussdb.functions import Window

    await DataRow.bulk_create(
        [
            DataRow(id=i, big=i * 10, duration=dt.timedelta(microseconds=i))
            for i in range(1, 4)
        ]
    )
    expressions = {
        "r": Window("rank", order_by=("id",)),
        "d": Window("dense_rank", order_by=("id",)),
        "a": Window("avg", "big", order_by=("id",), rows=(None, None)),
        "lo": Window("min", "big", order_by=("id",), rows=(-1, 1)),
        "hi": Window("max", "big", order_by=("id",), rows=(-1, 1)),
        "n": Window("count", "id", order_by=("id",), rows=(None, 0)),
        "prev": Window("lag", "big", order_by=("id",)),
        "next": Window("lead", "big", order_by=("id",)),
    }
    rows = await DataRow.annotate(**expressions).order_by("id").values(*expressions)
    assert [r["r"] for r in rows] == [1, 2, 3]
    assert [r["d"] for r in rows] == [1, 2, 3]
    assert [r["a"] for r in rows] == [20, 20, 20]
    assert [r["lo"] for r in rows] == [10, 10, 20]
    assert [r["hi"] for r in rows] == [20, 30, 30]
    assert [r["n"] for r in rows] == [1, 2, 3]
    assert [r["prev"] for r in rows] == [None, 10, 20]
    assert [r["next"] for r in rows] == [20, 30, None]
    await DataRow.filter(id=1).update(duration=F("duration") + 2)
    assert (await DataRow.get(id=1)).duration == dt.timedelta(microseconds=3)


async def test_numeric_overflow_and_stream_failure_recovery(db):
    import gaussdb

    with pytest.raises(OperationalError):
        await DataRow.create(id=1, small=32768)
    with pytest.raises(OperationalError):
        await DataRow.create(id=2, big=9223372036854775808)
    # The low-level streaming API preserves driver exception classes.
    with pytest.raises(gaussdb.ProgrammingError):
        async with db.stream_query("SELECT nonexistent_tortoise_function()") as rows:
            await anext(rows)
    await DataRow.create(id=3)
    assert await DataRow.all().count() == 1


async def test_introspection_views_and_missing_schema(db):
    await db.execute_script(
        f'CREATE VIEW "{SCHEMA}".row_view AS SELECT id FROM "{SCHEMA}".data_rows'
    )
    info = await db.inspect_schema()
    assert {"name": "row_view", "kind": "v"} in info["relations"]
    assert any(
        c["table_name"] == "row_view" and c["name"] == "id" for c in info["columns"]
    )
    missing = await db.inspect_schema("absent_" + uuid.uuid4().hex[:10])
    assert all(not value for key, value in missing.items() if key != "schema")


async def test_multi_app_concurrent_data_migrations(db, tmp_path, monkeypatch):
    from tortoise_gaussdb.migrations import GaussDBMigrationExecutor
    from tortoise.migrations.executor import MigrationTarget

    monkeypatch.syspath_prepend(str(tmp_path))
    packages = ["mig_a_" + uuid.uuid4().hex, "mig_b_" + uuid.uuid4().hex]
    create_sql = f'CREATE TABLE "{SCHEMA}".migration_data (id integer PRIMARY KEY)'
    if db.deployment == "distributed":
        create_sql += " DISTRIBUTE BY REPLICATION"
    drop_sql = f'DROP TABLE "{SCHEMA}".migration_data'
    for name in packages:
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("")
    prefix = "from tortoise.migrations.migration import Migration as Base\nfrom tortoise.migrations.operations import RunSQL, RunPython\n"
    (tmp_path / packages[0] / "0001_initial.py").write_text(
        prefix
        + f"""
class Migration(Base):
    initial = True
    dependencies = []
    operations = [RunSQL({create_sql!r}, {drop_sql!r})]
"""
    )
    insert_sql = f'INSERT INTO "{SCHEMA}".migration_data VALUES (1)'
    delete_sql = f'DELETE FROM "{SCHEMA}".migration_data'
    (tmp_path / packages[1] / "0001_initial.py").write_text(
        prefix
        + f"""
async def forward(apps, editor):
    await editor.client.execute_query({insert_sql!r})
async def backward(apps, editor):
    await editor.client.execute_query({delete_sql!r})
class Migration(Base):
    dependencies = [('models', '0001_initial')]
    operations = [RunPython(forward, backward)]
"""
    )
    apps = {
        "models": {"models": [__name__], "migrations": packages[0]},
        "secondary": {"models": [], "migrations": packages[1]},
    }
    first = GaussDBMigrationExecutor(db, apps)
    second = GaussDBMigrationExecutor(db, apps)
    # Bootstrap before parallel deployment runners; first-ever bootstrap remains serial.
    await first.recorder.ensure_schema(first._schema_editor(atomic=False))
    await first.migrate([MigrationTarget("models", "__latest__")])
    assert len(await first.recorder.applied_migrations()) == 1
    await asyncio.gather(first.migrate(), second.migrate())
    assert len(await first.recorder.applied_migrations()) == 2
    assert await db.execute_query_dict(f'SELECT id FROM "{SCHEMA}".migration_data') == [
        {"id": 1}
    ]
    await first.migrate([MigrationTarget("secondary", "__first__")])
    assert (
        await db.execute_query_dict(f'SELECT id FROM "{SCHEMA}".migration_data') == []
    )


async def test_sqlite_backend_coexists(db):
    from tortoise.backends.sqlite.client import SqliteClient
    from tortoise.backends.base_postgres.executor import BasePostgresExecutor
    from tortoise.filters import json_filter
    from tortoise_gaussdb.executor import GaussDBExecutor

    assert (
        BasePostgresExecutor.FILTER_FUNC_OVERRIDE[json_filter]
        is not GaussDBExecutor.FILTER_FUNC_OVERRIDE[json_filter]
    )
    sqlite = SqliteClient(file_path=":memory:", connection_name="sqlite_probe")
    try:
        await sqlite.create_connection(True)
        await sqlite.execute_script("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        await sqlite.execute_query("INSERT INTO probe VALUES (?)", [1])
        assert await sqlite.execute_query_dict("SELECT id FROM probe") == [{"id": 1}]
        await DataRow.create(id=7)
        assert await DataRow.all().count() == 1
    finally:
        await sqlite.close()
