import asyncio
import datetime
import decimal
import os
import uuid

import pytest
import pytest_asyncio
from tortoise import Tortoise, Model, fields
from tortoise.expressions import F, Q
from tortoise.exceptions import (
    IntegrityError,
    OperationalError,
    DoesNotExist,
    MultipleObjectsReturned,
)
from tortoise.functions import Sum
from tortoise.transactions import in_transaction
from tortoise_gaussdb.models import GaussDBModel

SCHEMA = "business_" + uuid.uuid4().hex[:10]


class Item(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=80, null=True)
    amount = fields.DecimalField(
        max_digits=18, decimal_places=4, default=decimal.Decimal("0")
    )
    active = fields.BooleanField(default=True)
    born = fields.DateField(null=True)
    blob = fields.BinaryField(null=True)
    tags = fields.ManyToManyField(
        "models.Tag",
        related_name="items",
        through="item_tags",
        backward_key="item_id",
        forward_key="tag_id",
        db_constraint=False,
    )

    class Meta:
        table = "items"
        schema = SCHEMA


class Tag(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=30)

    class Meta:
        table = "tags"
        schema = SCHEMA


class Child(Model):
    id = fields.IntField(primary_key=True)
    parent = fields.ForeignKeyField(
        "models.Item", related_name="children", db_constraint=False
    )
    value = fields.IntField(default=0)

    class Meta:
        table = "children"
        schema = SCHEMA


class Profile(GaussDBModel):
    id = fields.IntField(primary_key=True)
    owner = fields.OneToOneField(
        "models.Item", related_name="profile", db_constraint=False,
        null=True, source_field="profile_owner_key",
    )

    class Meta:
        table = "profiles"
        schema = SCHEMA


class ConflictRow(Model):
    id = fields.IntField(primary_key=True, generated=False, source_field="row_id")
    code = fields.CharField(max_length=30, unique=True)
    value = fields.IntField(default=0)
    amount = fields.DecimalField(max_digits=12, decimal_places=2, null=True)

    class Meta:
        table = "upsert_rows"
        schema = SCHEMA


@pytest_asyncio.fixture(params=["CENTRAL", "DIST"])
async def db(request):
    tag = request.param
    if not os.getenv("CENTRAL_PASSWORD"):
        pytest.fail("Live tests require CENTRAL_PASSWORD; no mock fallback")
    config = {
        "connections": {
            "default": {
                "engine": "tortoise_gaussdb",
                "credentials": {
                    "host": os.getenv("TEST_HOST", "host.docker.internal"),
                    "port": os.environ[tag + "_PORT"],
                    "database": os.environ[tag + "_DB"],
                    "user": os.environ[tag + "_USER"],
                    "password": os.environ.get(
                        tag + "_PASSWORD", os.environ["CENTRAL_PASSWORD"]
                    ),
                    "deployment": "distributed" if tag == "DIST" else "centralized",
                    "schema": SCHEMA,
                    "distributions": {
                        **{
                            f"{SCHEMA}.{t}": {"type": "HASH", "field": "id"}
                            for t in ["items", "children", "tags"]
                        },
                        f"{SCHEMA}.item_tags": {"type": "HASH", "field": "item_id"},
                        f"{SCHEMA}.profiles": {"type": "REPLICATION"},
                        f"{SCHEMA}.upsert_rows": {"type": "REPLICATION"},
                    },
                    "minsize": 1,
                    "maxsize": 3,
                    "timeout": 3,
                },
            }
        },
        "apps": {"models": {"models": [__name__]}},
    }
    await Tortoise.init(config=config)
    conn = Tortoise.get_connection("default")
    try:
        await Tortoise.generate_schemas(safe=True)
        yield conn
    finally:
        try:
            await conn.execute_script(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        finally:
            await conn.close()
            await Tortoise.close_connections()


async def test_DDL_01_standard_safe_repeated(db):
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.generate_schemas(safe=True)
    assert await Item.all().count() == 0


async def test_MIG_05_add_logical_foreign_key(db):
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor

    editor = GaussDBSchemaEditor(db, atomic=False)
    relation = Child._meta.fields_map["parent"]
    await editor.remove_field(Child, relation)
    await editor.add_field(Child, "parent")

    parent = await Item.create(name="migration parent")
    child = await Child.create(parent=parent, value=42)
    loaded = await Child.get(id=child.id).select_related("parent")
    assert loaded.parent.id == parent.id
    assert loaded.value == 42
    rows = await db.execute_query_dict(
        "SELECT con.oid FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace n ON n.oid=rel.relnamespace "
        "WHERE n.nspname=%s AND rel.relname=%s AND con.contype='f'",
        [SCHEMA, "children"],
    )
    assert rows == []
    # Reverse the relation migration, then reapply on populated data. A
    # nonnullable relation must fail rather than silently backfill a parent.
    await editor.remove_field(Child, relation)
    with pytest.raises(IntegrityError):
        await editor.add_field(Child, "parent")
    await Child.all().delete()
    await editor.add_field(Child, "parent")


async def test_MIG_05_add_many_to_many(db):
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor

    editor = GaussDBSchemaEditor(db, atomic=False)
    relation = Item._meta.fields_map["tags"]
    await editor.remove_field(Item, relation)
    await editor.add_field(Item, "tags")

    item = await Item.create(name="migration m2m")
    tag = await Tag.create(name="migration tag")
    await item.tags.add(tag)
    await item.tags.add(tag)
    assert await item.tags.all().count() == 1
    if db.deployment == "distributed":
        rows = await db.execute_query_dict(
            "SELECT x.pclocatortype FROM pgxc_class x "
            "JOIN pg_class c ON c.oid=x.pcrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s",
            [SCHEMA, "item_tags"],
        )
        assert rows[0]["pclocatortype"] == "H"
    await item.tags.clear()
    await editor.remove_field(Item, relation)
    await editor.add_field(Item, "tags")


async def test_REL_02_one_to_one_migration(db):
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor

    editor = GaussDBSchemaEditor(db, atomic=False)
    relation = Profile._meta.fields_map["owner"]
    await editor.remove_field(Profile, relation)
    await editor.add_field(Profile, "owner")
    owner = await Item.create(name="one-to-one owner")
    profile = await Profile.create(owner=owner)
    loaded = await Profile.get(id=profile.id).select_related("owner")
    assert loaded.owner.id == owner.id
    assert (await owner.profile).id == profile.id
    with pytest.raises(IntegrityError):
        await Profile.create(owner=owner)
    await Profile.create(owner=None)
    await editor.remove_field(Profile, relation)
    await editor.add_field(Profile, "owner")
    await profile.refresh_from_db()
    assert profile.owner_id is None
    assert await profile.owner is None
    profile.owner = owner
    await profile.refresh_from_db(fields=["id"])
    assert profile.owner_id == owner.id
    await profile.refresh_from_db(fields=["owner_id"])
    assert profile.owner_id is None


async def test_DIST_01_explicit_layout(db):
    if db.deployment == "distributed":
        rows = await db.execute_query_dict(
            "SELECT x.pclocatortype FROM pgxc_class x JOIN pg_class c ON c.oid=x.pcrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",
            [SCHEMA, "items"],
        )
        assert rows[0]["pclocatortype"] == "H"
    else:
        assert "DISTRIBUTE BY" not in db.schema_generator(db).get_create_schema_sql()


async def test_MIG_02_schema_qualified_indexes(db):
    from tortoise.indexes import Index
    from tortoise.migrations.constraints import UniqueConstraint
    from tortoise_gaussdb.migrations import GaussDBSchemaEditor

    editor = GaussDBSchemaEditor(db, atomic=False)
    old = Index(fields=["name"], name="migration_name_idx")
    new = Index(fields=["name"], name="migration_renamed_idx")
    await editor.add_index(Item, old)
    await editor.rename_index(Item, old, new)
    rows = await db.execute_query_dict(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relname=%s", [SCHEMA, new.name]
    )
    assert len(rows) == 1
    await editor.remove_index(Item, new)
    partial = UniqueConstraint(fields=("id", "name"), name="migration_partial_idx", condition='"name" IS NOT NULL')
    await editor.add_constraint(Item, partial)
    await editor.remove_constraint(Item, partial)
    rows = await db.execute_query_dict(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relname IN (%s,%s,%s)",
        [SCHEMA, old.name, new.name, partial.name],
    )
    assert rows == []


@pytest.mark.parametrize(
    "value",
    [
        decimal.Decimal("0"),
        decimal.Decimal("-123456789.1234"),
        decimal.Decimal("99999999999999.9999"),
    ],
)
async def test_TYPE_02_decimal(db, value):
    item = await Item.create(
        name="中文😀", amount=value, born=datetime.date(2024, 2, 29), blob=b"\x00\xff"
    )
    got = await Item.get(id=item.id)
    assert got.amount == value and isinstance(got.amount, decimal.Decimal)
    assert got.born == datetime.date(2024, 2, 29)
    assert got.blob == b"\x00\xff" and got.name == "中文😀" and got.active is True


async def test_TYPE_06_empty_string(db):
    item = await Item.create(name="")
    assert (await Item.get(id=item.id)).name is None


async def test_CRUD_queries_relations(db):
    a = await Item.create(name="Robert'); DROP TABLE items;--")
    b = await Item.create(name="second")
    assert a.id != b.id
    await Child.create(parent=a, value=2)
    assert len(await a.children.all()) == 1
    assert (await Child.all().select_related("parent").first()).parent.id == a.id
    assert (
        len((await Item.filter(id=a.id).prefetch_related("children").first()).children)
        == 1
    )
    assert await Item.filter(Q(id=a.id) | Q(id=b.id)).count() == 2
    assert await Item.filter(id__in=[]).count() == 0
    assert await Item.filter(id=a.id).update(amount=F("amount") + 1) == 1
    assert await Item.filter(id=-1).delete() == 0
    assert (await Item.filter(id=a.id).values_list("name", flat=True))[0] == a.name
    with pytest.raises(DoesNotExist):
        await Item.get(id=-1)
    with pytest.raises(MultipleObjectsReturned):
        await Item.get(active=True)


async def test_BULK_01_02_04(db):
    await Item.bulk_create([Item(id=i, name=str(i)) for i in range(1, 8)], batch_size=3)
    await Item.bulk_create(
        [Item(id=1, name="ignored"), Item(id=8, name="new")], ignore_conflicts=True
    )
    assert await Item.all().count() == 8
    assert (await Item.get(id=1)).name == "1"
    rows = await Item.all().order_by("id")
    for row in rows:
        row.amount = decimal.Decimal(row.id)
    await Item.bulk_update(rows, fields=["amount"], batch_size=3)
    assert (await Item.all().annotate(total=Sum("amount")).values("total"))[0][
        "total"
    ] == 36
    with pytest.raises(OperationalError):
        await Item.bulk_create([Item(id=1)], on_conflict=["id"], update_fields=["name"])


async def test_TX_01_02_04(db):
    async with in_transaction():
        await Item.create(id=100, name="outer")
        with pytest.raises(RuntimeError):
            async with in_transaction():
                await Item.create(id=101, name="inner")
                raise RuntimeError("rollback savepoint")
    assert await Item.filter(id=100).exists()
    assert not await Item.filter(id=101).exists()
    with pytest.raises(IntegrityError):
        async with in_transaction():
            await Item.create(id=102, name="rollback")
            await Item.create(id=100)
    assert not await Item.filter(id=102).exists()
    assert await Item.all().count() == 1


async def test_ASYNC_01_02_TX_05(db):
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    await asyncio.gather(db.execute_query("SELECT pg_sleep(0.25)"), heartbeat())
    assert ticks == 20
    await asyncio.gather(*(Item.create(name=str(i)) for i in range(20)))
    assert await Item.all().count() == 20
    task = asyncio.create_task(db.execute_query("SELECT pg_sleep(10)"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await db.execute_query("SELECT 42 AS value"))[1][0]["value"] == 42


async def test_MIG_01_02_03_04_native_operations(db, tmp_path, monkeypatch):
    from tortoise_gaussdb.migrations import GaussDBMigrationExecutor
    from tortoise.migrations.executor import MigrationTarget
    import importlib

    package = "migration_" + uuid.uuid4().hex
    folder = tmp_path / package
    folder.mkdir()
    (folder / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    prefix = "from tortoise import fields\nfrom tortoise.migrations.migration import Migration as Base\nfrom tortoise.migrations.operations import CreateModel, AddField, RenameField, RunSQL\n"
    (folder / "0001_initial.py").write_text(
        prefix
        + f"""
class Migration(Base):
    initial=True
    dependencies=[]
    operations=[CreateModel(name='Archive', fields=[('id',fields.IntField(primary_key=True)),('name',fields.CharField(max_length=80))],options={{'table':'archive','schema':{SCHEMA!r}}})]
"""
    )
    (folder / "0002_note.py").write_text(
        prefix
        + """
class Migration(Base):
    dependencies=[('models','0001_initial')]
    operations=[AddField('Archive','note',fields.CharField(max_length=40,null=True,description="备注 'quoted' 100%")),RenameField('Archive','name','title'),AddField('Archive','parent',fields.ForeignKeyField('models.Archive',null=True,db_constraint=False,source_field='ancestor_key',related_name='descendants'))]
"""
    )
    db.distributions[f"{SCHEMA}.archive"] = {"type": "HASH", "field": "id"}
    executor = GaussDBMigrationExecutor(
        db,
        {
            "models": {
                "models": [__name__],
                "migrations": package,
                "default_connection": "default",
            }
        },
    )
    sql = "\n".join(await executor.collect_sql("models", "0001"))
    assert "CREATE TABLE" in sql
    assert ("DISTRIBUTE BY HASH" in sql) == (db.deployment == "distributed")
    assert not await executor.recorder.applied_migrations()
    await executor.migrate([MigrationTarget("models", "0001_initial")])
    await db.execute_query(
        f'INSERT INTO "{SCHEMA}".archive(name) VALUES(%s)', ["preserved"]
    )
    await executor.migrate()
    await executor.migrate()
    assert len(await executor.recorder.applied_migrations()) == 2
    row = (await db.execute_query(f'SELECT title,note FROM "{SCHEMA}".archive'))[1][0]
    assert row == {"title": "preserved", "note": None}
    comments = await db.execute_query_dict(
        "SELECT col_description(c.oid,a.attnum) AS comment FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname=%s AND c.relname=%s AND a.attname=%s",
        [SCHEMA, "archive", "note"],
    )
    assert comments[0]["comment"] == "备注 'quoted' 100%"

    assert (await db.execute_query(f'SELECT ancestor_key FROM "{SCHEMA}".archive'))[1][0] == {"ancestor_key": None}
    await executor.migrate([MigrationTarget("models", "0001_initial")])
    assert (await db.execute_query(f'SELECT name FROM "{SCHEMA}".archive'))[1][0][
        "name"
    ] == "preserved"
    # Reapply then prove DDL and history rollback together on an actual failure.
    await executor.migrate()
    (folder / "0003_failure.py").write_text(
        prefix
        + f'''
class Migration(Base):
    dependencies=[('models','0002_note')]
    operations=[AddField('Archive','failed_column',fields.IntField(null=True)),RunSQL('SELECT * FROM "{SCHEMA}".missing_table')]
'''
    )
    importlib.invalidate_caches()
    executor._full_plan_cache = None
    with pytest.raises(Exception, match="missing_table"):
        await executor.migrate()
    assert len(await executor.recorder.applied_migrations()) == 2
    _, columns = await db.execute_query(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        [SCHEMA, "archive"],
    )
    assert "failed_column" not in [r["column_name"] for r in columns]
    await executor.migrate([MigrationTarget("models", "__first__")])
    assert await executor.recorder.applied_migrations() == []


async def test_REL_03_m2m(db):
    item = await Item.create(name="m2m")
    tags = [await Tag.create(name=str(i)) for i in range(3)]
    await item.tags.add(*tags)
    await item.tags.add(tags[0])
    assert await item.tags.all().count() == 3
    await item.tags.remove(tags[0])
    assert await item.tags.all().count() == 2
    fetched = await Item.filter(id=item.id).prefetch_related("tags").first()
    assert len(fetched.tags) == 2
    await item.tags.clear()
    assert await item.tags.all().count() == 0


async def test_ASYNC_02_pool_timeout_and_recovery(db):
    import gaussdb_pool

    # Hold all 3 connections, then force a bounded acquire timeout.
    held = [await db._pool.getconn() for _ in range(3)]
    try:
        with pytest.raises(gaussdb_pool.PoolTimeout):
            await db._pool.getconn(timeout=0.05)
    finally:
        for conn in held:
            await db._pool.putconn(conn)
    assert (await db.execute_query("SELECT 1 AS ok"))[1][0]["ok"] == 1


async def test_DIST_03_04_cross_dn(db):
    await Item.bulk_create([Item(id=i, name=str(i)) for i in range(1, 101)])
    with pytest.raises(RuntimeError):
        async with in_transaction():
            await Item.all().update(amount=7)
            raise RuntimeError("cross shard rollback")
    assert await Item.filter(amount=0).count() == 100
    async with in_transaction():
        await Item.all().update(amount=8)
    assert await Item.filter(amount=8).count() == 100
    if db.deployment == "distributed":
        _, plan = await db.execute_query(
            f'EXPLAIN SELECT sum(amount) FROM "{SCHEMA}".items'
        )
        assert "All datanodes" in str(plan)


async def test_TYPE_08_binary_megabyte(db):
    import hashlib

    value = bytes(range(256)) * 4096
    item = await Item.create(blob=value)
    result = await Item.get(id=item.id)
    assert hashlib.sha256(result.blob).digest() == hashlib.sha256(value).digest()


async def test_QUERY_07_regex_TX_06_lock(db):
    import gaussdb

    item = await Item.create(name="abc123")
    assert await Item.filter(name__posix_regex="^[a-z]+[0-9]+$").count() == 1
    async with in_transaction():
        locked = await Item.filter(id=item.id).select_for_update().get()
        assert locked.id == item.id
        other = await db._pool.getconn()
        try:
            async with other.transaction():
                with pytest.raises(gaussdb.errors.LockNotAvailable):
                    await other.execute(
                        f'SELECT * FROM "{SCHEMA}".items WHERE id=%s FOR UPDATE NOWAIT',
                        [item.id],
                    )
        finally:
            await db._pool.putconn(other)


async def test_E2E_02_fastapi(db, monkeypatch):
    import importlib
    import httpx
    from asgi_lifespan import LifespanManager

    monkeypatch.setenv("GAUSS_SCHEMA", SCHEMA)
    monkeypatch.setenv("GAUSS_DEMO_CREATE_SCHEMA", "1")
    from examples import models

    importlib.reload(models)
    from examples import fastapi_app

    importlib.reload(fastapi_app)
    # Reuse the fixture's credentials without ever printing them.
    config = {
        "connections": {
            "default": {
                "engine": "tortoise_gaussdb",
                "credentials": {
                    "host": db.host,
                    "port": db.port,
                    "user": db.user,
                    "password": db.password,
                    "database": db.database,
                    "schema": SCHEMA,
                    "deployment": db.deployment,
                    "distributions": {
                        f"{SCHEMA}.orders": {"type": "HASH", "field": "id"}
                    },
                },
            }
        },
        "apps": {"models": {"models": ["examples.models"]}},
    }
    app = fastapi_app.create_app(config)
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            responses = await asyncio.gather(
                *(
                    http.post(
                        "/orders", json={"customer": f"客户{i}", "amount": "12.34"}
                    )
                    for i in range(10)
                )
            )
            assert all(r.status_code == 201 for r in responses)
            ids = {r.json()["id"] for r in responses}
            assert len(ids) == 10
            for pk in ids:
                response = await http.get(f"/orders/{pk}")
                assert (
                    response.status_code == 200 and response.json()["amount"] == "12.34"
                )
            assert (await http.get("/orders/-1")).status_code == 404
            assert (
                await http.post("/orders", json={"customer": "", "amount": "1"})
            ).status_code == 422


async def test_MIG_01_cli_generation_apply_and_preview(db, tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2]
    shutil.copytree(
        source / "examples",
        tmp_path / "examples",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    env = os.environ.copy()
    env.update(
        GAUSS_SCHEMA=SCHEMA,
        GAUSS_HOST=db.host,
        GAUSS_PORT=str(db.port),
        GAUSS_DATABASE=db.database,
        GAUSS_USER=db.user,
        GAUSS_PASSWORD=db.password,
        GAUSS_DEPLOYMENT=db.deployment,
        PYTHONPATH=str(source / "src") + os.pathsep + str(tmp_path),
    )

    def run(*args, offline=False):
        child_env = env.copy()
        if offline:
            child_env.update(GAUSS_HOST="127.0.0.1", GAUSS_PORT="1")
        result = subprocess.run(
            args,
            cwd=tmp_path,
            env=child_env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + "\n" + result.stderr
        return result.stdout

    run("tortoise", "-c", "examples.config.CONFIG", "init")
    run("tortoise", "-c", "examples.config.CONFIG", "makemigrations")
    files = list((tmp_path / "examples" / "migrations").glob("0*.py"))
    assert len(files) == 1
    name = files[0].stem
    # Invalid database address proves preview is truly offline.
    sql = run(
        sys.executable,
        "-m",
        "tortoise_gaussdb.migrations",
        "sqlmigrate",
        "-c",
        "examples.config:CONFIG",
        "--app",
        "models",
        "--name",
        name,
        offline=True,
    )
    assert "CREATE TABLE" in sql and "CREATE SCHEMA IF NOT EXISTS" not in sql
    run(
        sys.executable,
        "-m",
        "tortoise_gaussdb.migrations",
        "migrate",
        "-c",
        "examples.config:CONFIG",
    )
    run(
        sys.executable,
        "-m",
        "tortoise_gaussdb.migrations",
        "migrate",
        "-c",
        "examples.config:CONFIG",
    )
    assert (
        await db.execute_query(
            f'SELECT count(*) AS n FROM "{SCHEMA}".tortoise_migrations'
        )
    )[1][0]["n"] == 1
    run(
        sys.executable,
        "-m",
        "tortoise_gaussdb.migrations",
        "migrate",
        "-c",
        "examples.config:CONFIG",
        "--app",
        "models",
        "--name",
        "__first__",
    )
    assert (
        await db.execute_query(
            f'SELECT count(*) AS n FROM "{SCHEMA}".tortoise_migrations'
        )
    )[1][0]["n"] == 0


@pytest.mark.parametrize("suffix", ["Case Space", "a'b\"c"])
async def test_DDL_04_quoted_schema(db, suffix):
    from tortoise_gaussdb.schema import create_schema_sql, quote_identifier

    name = "quoted_" + uuid.uuid4().hex[:8] + "_" + suffix
    try:
        await db.execute_script(create_schema_sql(name))
        await db.execute_script(create_schema_sql(name))
        rows = await db.execute_query_dict(
            "SELECT nspname FROM pg_namespace WHERE nspname=%s", [name]
        )
        assert rows == [{"nspname": name}]
    finally:
        await db.execute_script(
            f"DROP SCHEMA IF EXISTS {quote_identifier(name)} RESTRICT"
        )


async def test_BULK_04_exact_target_upsert(db):
    await ConflictRow.create(id=1,code="first",value=1)
    rows = [ConflictRow(id=1,code="first",value=42,amount=decimal.Decimal("12.34")),ConflictRow(id=2,code="second",value=20)]
    await ConflictRow.bulk_create(rows,update_fields=["value","amount"],on_conflict=["id"])
    first=await ConflictRow.get(id=1)
    assert first.value==42 and first.amount==decimal.Decimal("12.34")
    assert (await ConflictRow.get(id=2)).amount is None
    # A different unique-key conflict must fail, not be broadly ignored.
    bad=[ConflictRow(id=3,code="third"),ConflictRow(id=4,code="first")]
    with pytest.raises(IntegrityError):
        await ConflictRow.bulk_create(bad,update_fields=["value"],on_conflict=["id"])
    assert not await ConflictRow.filter(id=3).exists()
    with pytest.raises(OperationalError,match="unique index"):
        await ConflictRow.bulk_create([ConflictRow(id=5,code="fifth")],update_fields=["amount"],on_conflict=["value"])
    from tortoise_gaussdb.client import GaussDBSQLQuery
    query=(GaussDBSQLQuery.into(ConflictRow._meta.basetable).columns("row_id","code","value","amount")
           .insert(1,"ignored",999,None).on_conflict("row_id").do_nothing())
    sql,params=query.get_parameterized_sql()
    await db.execute_query(sql,params)
    assert (await ConflictRow.get(id=1)).value==42
