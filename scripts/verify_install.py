"""Run with a clean venv and PYTHONPATH unset; credentials remain in env."""

import asyncio
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys
import uuid

import tortoise_gaussdb
from tortoise import Tortoise, Model, fields
from tortoise.transactions import in_transaction

assert Path(tortoise_gaussdb.__file__).is_relative_to(Path(sys.prefix)), (
    tortoise_gaussdb.__file__
)
tag = os.environ["CHECK_TARGET"]
schema = "install_" + uuid.uuid4().hex[:10]


class InstalledItem(Model):
    id = fields.IntField(primary_key=True)
    value = fields.CharField(max_length=20)

    class Meta:
        table = "items"
        schema = schema


async def main():
    await Tortoise.init(
        config={
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
                        "schema": schema,
                        "deployment": "distributed" if tag == "DIST" else "centralized",
                        "distributions": {
                            f"{schema}.items": {"type": "HASH", "field": "id"}
                        },
                    },
                }
            },
            "apps": {"models": {"models": ["__main__"]}},
        }
    )
    conn = Tortoise.get_connection("default")
    try:
        await Tortoise.generate_schemas()
        row = await InstalledItem.create(value="installed")
        assert (await InstalledItem.get(id=row.id)).value == "installed"
        try:
            async with in_transaction():
                await InstalledItem.create(value="rollback")
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        assert await InstalledItem.all().count() == 1
        version = (await conn.execute_query("SELECT version() AS version"))[1][0][
            "version"
        ]
        versions = {
            p: metadata.version(p)
            for p in [
                "tortoise-gaussdb",
                "tortoise-orm",
                "gaussdb",
                "gaussdb-pool",
                "pypika-tortoise",
                "anyio",
            ]
        }
        print(
            json.dumps(
                {
                    "target": tag,
                    "status": "PASS",
                    "version": version,
                    "packages": versions,
                    "adapter_path": tortoise_gaussdb.__file__,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await conn.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await Tortoise.close_connections()


asyncio.run(main())
