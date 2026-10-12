from unittest.mock import AsyncMock
import pytest
from tortoise.exceptions import ConfigurationError, DBConnectionError
from tortoise_gaussdb.client import GaussDBClient


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deployment": "wrong"},
        {"allow_default_distribution": "false"},
        {"skip_mode_check": "false"},
    ],
)
def test_config_no_truthy_strings(kwargs):
    with pytest.raises(ConfigurationError):
        GaussDBClient(connection_name="unit", **kwargs)


@pytest.mark.parametrize(
    "compat,version",
    [
        ("PG", "GaussDB Kernel 507.0.0"),
        ("MYSQL", "GaussDB Kernel 507.0.0"),
        ("A", "PostgreSQL 15.0"),
        ("ORA", "GaussDB Kernel 508.0.0"),
    ],
)
async def test_mode_version_fail_closed(compat, version):
    client = GaussDBClient(connection_name="unit")
    client.execute_query = AsyncMock(
        return_value=(1, [{"db": "test", "compat": compat, "version": version}])
    )
    with pytest.raises(DBConnectionError):
        await client._preflight_mode_check()
    assert not client._mode_checked


async def test_failed_preflight_closes_pool():
    client = GaussDBClient(connection_name="unit")
    pool = AsyncMock()
    client.create_pool = AsyncMock(return_value=pool)
    client._post_connect = AsyncMock()
    client._preflight_mode_check = AsyncMock(
        side_effect=DBConnectionError("wrong mode")
    )
    with pytest.raises(DBConnectionError):
        await client.create_connection(True)
    assert client._pool is None
    pool.close.assert_awaited_once()
