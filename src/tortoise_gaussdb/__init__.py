"""GaussDB backend for Tortoise-ORM.

Target: GaussDB 507, Oracle (O) compatibility mode, both centralized and
distributed deployments. Built on the ``gaussdb`` async driver (psycopg3 fork)
and ``gaussdb_pool`` async connection pool.

Public entry point: ``tortoise_gaussdb`` — pass as the ``engine`` in a Tortoise
config dict:

    {
        "connections": {
            "default": {
                "engine": "tortoise_gaussdb",
                "credentials": {
                    "host": "127.0.0.1", "port": 55452,
                    "user": "tortoise_lab", "password": "...",
                    "database": "tortoise_test",
                },
            },
        },
        ...
    }
"""

from tortoise_gaussdb.client import GaussDBClient

client_class = GaussDBClient

__version__ = "0.3.0"

__all__ = ["client_class", "GaussDBClient", "__version__"]
