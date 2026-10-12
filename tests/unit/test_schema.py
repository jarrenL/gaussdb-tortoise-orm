import pytest
from tortoise import fields, Model, Tortoise
from tortoise.exceptions import OperationalError
from tortoise_gaussdb.client import GaussDBClient, GaussDBSQLQuery
from tortoise_gaussdb.schema import GaussDBSchemaGenerator, create_schema_sql
from tortoise_gaussdb.distributed import DistributionError
from pypika_tortoise import Table


class Item(Model):
    id = fields.IntField(primary_key=True, source_field="item_id")
    name = fields.CharField(max_length=40)

    class Meta:
        table = "items"
        schema = "business"


@pytest.mark.parametrize("deployment", ["centralized", "distributed"])
async def test_distribution_standard_schema(deployment):
    await Tortoise.init(
        config={
            "connections": {
                "default": {
                    "engine": "tortoise_gaussdb",
                    "credentials": {
                        "deployment": deployment,
                        "distributions": {
                            "business.items": {"type": "HASH", "field": "item_id"}
                        },
                    },
                }
            },
            "apps": {"models": {"models": [__name__]}},
        }
    )
    try:
        sql = GaussDBSchemaGenerator(
            Tortoise.get_connection("default")
        ).get_create_schema_sql()
        assert ('DISTRIBUTE BY HASH("item_id")' in sql) == (deployment == "distributed")
        assert "CREATE SCHEMA IF NOT EXISTS" not in sql
        assert "duplicate_schema" in sql
    finally:
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "dist,match",
    [
        ({}, "Missing"),
        ({"type": "HASH", "field": "missing"}, "unknown"),
        ({"type": "HASH", "field": "name"}, "unique key"),
    ],
)
async def test_invalid_distribution(dist, match):
    client = GaussDBClient(
        connection_name="test",
        deployment="distributed",
        distributions={"business.items": dist} if dist else {},
    )
    with pytest.raises(DistributionError, match=match):
        GaussDBSchemaGenerator(client)._model_distribution(Item)


@pytest.mark.parametrize(
    "schema", ["sales", "Sales Team", "quote'and\"name", "$gaussdb_schema$"]
)
def test_schema_quoting(schema):
    sql = create_schema_sql(schema)
    assert "duplicate_schema" in sql
    assert "IF NOT EXISTS" not in sql
    assert create_schema_sql(schema, False).startswith('CREATE SCHEMA "')


def test_conflict_sql():
    table = Table("items")
    sql = str(
        GaussDBSQLQuery.into(table).columns("id").insert(1).on_conflict().do_nothing()
    )
    assert "ON DUPLICATE KEY UPDATE NOTHING" in sql
    assert "ON CONFLICT" not in sql


def test_targeted_conflict_compiles_exact_merge():
    q = GaussDBSQLQuery.into("items").columns("id", "name").insert(1, "value").on_conflict("id").do_update("name")
    sql = str(q)
    assert "MERGE INTO" in sql
    assert 't."id"=s."id"' in sql
    assert '"name"=s."name"' in sql
    assert "ON DUPLICATE" not in sql


def test_targeted_conflict_key_update_rejected():
    q = GaussDBSQLQuery.into("items").columns("id").insert(1).on_conflict("id").do_update("id")
    with pytest.raises(OperationalError):
        str(q)
