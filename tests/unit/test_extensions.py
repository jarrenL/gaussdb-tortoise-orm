import pytest
from tortoise.exceptions import ConfigurationError
from tortoise_gaussdb.client import GaussDBClient
from tortoise_gaussdb.functions import Window, Extract
from tortoise_gaussdb.fields import JSONField


@pytest.mark.parametrize(
    "level", ["SERIALIZABLE", "READ UNCOMMITTED", "nonsense", 1, None]
)
def test_reject_misleading_isolation(level):
    with pytest.raises(ConfigurationError):
        GaussDBClient(connection_name="unit", isolation_level=level)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"function": "row_number"},
        {"function": "sum", "order_by": ("id",)},
        {"function": "evil()", "field": "id", "order_by": ("id",)},
        {"function": "sum", "field": "id", "order_by": ("id",), "rows": (1, -1)},
        {"function": "rank", "order_by": ("id",), "rows": (None, 0)},
    ],
)
def test_window_reject_invalid_contract(kwargs):
    with pytest.raises(ConfigurationError):
        Window(**kwargs)


def test_date_part_not_sql():
    with pytest.raises(ConfigurationError):
        Extract("created", "day');DROP TABLE t;--")


def test_unicode_json_encoding_preserves_backslashes():
    field = JSONField()
    import json

    value = {"nested": {"a": "值'\\😀"}, "literal": r"\u4e2d"}
    assert json.loads(field.to_db_value(value, None)) == value
    assert field.to_db_value(None, None) is None
