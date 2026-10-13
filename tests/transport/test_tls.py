"""Opt-in TLS contracts against a dedicated real GaussDB server.

Requires TLS_TEST_HOST/PORT/DATABASE/USER/PASSWORD_FILE/CA_FILE.
The server must require TLS and the account must own a disposable database.
"""

import asyncio
import os
import socket
import subprocess
from pathlib import Path
import pytest
from tortoise_gaussdb.client import GaussDBClient
from tortoise.exceptions import DBConnectionError


@pytest.fixture
def credentials():
    if not os.getenv("TLS_TEST_HOST"):
        pytest.skip(
            "Dedicated TLS server not configured; see docs/extended-validation.md"
        )
    return {
        "host": os.environ["TLS_TEST_HOST"],
        "port": int(os.environ["TLS_TEST_PORT"]),
        "database": os.environ["TLS_TEST_DATABASE"],
        "user": os.environ["TLS_TEST_USER"],
        "password": Path(os.environ["TLS_TEST_PASSWORD_FILE"]).read_text().strip(),
        "deployment": "centralized",
        "minsize": 1,
        "maxsize": 1,
        "timeout": 2,
        "server_settings": {
            "sslmode": "verify-full",
            "sslrootcert": os.environ["TLS_TEST_CA_FILE"],
        },
    }


async def test_verified_tls(credentials):
    client = GaussDBClient(connection_name="tls", **credentials)
    try:
        await client.create_connection(True)
        assert (await client.execute_query_dict("SHOW ssl")) == [{"ssl": "on"}]
        assert (await client.execute_query_dict("SELECT 42 AS value")) == [
            {"value": 42}
        ]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "failure",
    ["hostname", "ca", "wrong_ca", "password", "user", "database", "port", "plaintext"],
)
async def test_tls_auth_rejection(credentials, failure, tmp_path):
    if failure == "hostname":
        credentials["server_settings"]["hostaddr"] = socket.gethostbyname(
            credentials["host"]
        )
        credentials["host"] = "wrong-hostname.invalid"
    elif failure == "ca":
        credentials["server_settings"]["sslrootcert"] = str(tmp_path / "missing-ca.crt")
    elif failure == "wrong_ca":
        cert = tmp_path / "untrusted-ca.crt"
        await asyncio.to_thread(
            subprocess.run,
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=Untrusted Test CA",
                "-keyout",
                str(tmp_path / "ca.key"),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
        cert.chmod(0o600)
        credentials["server_settings"]["sslrootcert"] = str(cert)
    elif failure == "password":
        credentials["password"] = "WrongPassword1!"
    elif failure == "user":
        credentials["user"] = "nonexistent_tortoise_user"
    elif failure == "database":
        credentials["database"] = "nonexistent_tortoise_database"
    elif failure == "port":
        credentials["port"] = 1
    elif failure == "plaintext":
        credentials["server_settings"] = {"sslmode": "disable"}
    client = GaussDBClient(connection_name="tls_negative", **credentials)
    try:
        with pytest.raises(DBConnectionError):
            await client.create_connection(True)
        assert client._pool is None
    finally:
        await client.close()


async def test_dead_idle_connection_replaced(credentials):
    client = GaussDBClient(connection_name="tls_recovery", **credentials)
    killer = GaussDBClient(connection_name="tls_killer", **credentials)
    try:
        await client.create_connection(True)
        await killer.create_connection(True)
        async with client.acquire_connection() as original_connection:
            pass
        old = (await client.execute_query_dict("SELECT pg_backend_pid() AS pid"))[0][
            "pid"
        ]
        result = await killer.execute_query_dict(
            "SELECT pg_terminate_backend(%s) AS stopped", [old]
        )
        assert result[0]["stopped"]
        new = (await client.execute_query_dict("SELECT pg_backend_pid() AS pid"))[0][
            "pid"
        ]
        async with client.acquire_connection() as replacement:
            assert replacement is not original_connection
        assert original_connection.closed
        assert isinstance(new, int)
        assert (await client.execute_query_dict("SELECT 42 AS value")) == [
            {"value": 42}
        ]
    finally:
        await client.close()
        await killer.close()


async def test_multihost_connection_fallback(credentials):
    credentials["host"] = "127.0.0.1," + credentials["host"]
    credentials["server_settings"]["connect_timeout"] = 2
    credentials["timeout"] = 5
    client = GaussDBClient(connection_name="tls_multihost", **credentials)
    try:
        await client.create_connection(True)
        assert (await client.execute_query_dict("SELECT 42 AS value")) == [
            {"value": 42}
        ]
    finally:
        await client.close()
