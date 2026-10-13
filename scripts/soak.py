"""Run a bounded mixed ORM load on disposable schemas in both O-mode instances.

python scripts/soak.py --seconds 1800
Connection environment matches .env.example; never reads or prints secrets.
"""

import argparse
import asyncio
import json
import os
import time
import types
import sys
import uuid
from tortoise import Tortoise, Model, fields
from tortoise.expressions import F
from tortoise.transactions import in_transaction


async def target(tag, seconds):
    schema = "soak_" + uuid.uuid4().hex[:12]

    class SoakRow(Model):
        id = fields.IntField(primary_key=True, generated=False)
        value = fields.IntField(default=0)

        class Meta:
            table = "soak_rows"

    SoakRow._meta.schema = schema
    module = types.ModuleType("soak_models_" + tag)
    module.SoakRow = SoakRow
    sys.modules[module.__name__] = module
    creds = {
        "host": os.getenv("TEST_HOST", "host.docker.internal"),
        "port": os.environ[tag + "_PORT"],
        "database": os.environ[tag + "_DB"],
        "user": os.environ[tag + "_USER"],
        "password": os.environ.get(tag + "_PASSWORD", os.environ["CENTRAL_PASSWORD"]),
        "deployment": "distributed" if tag == "DIST" else "centralized",
        "schema": schema,
        "minsize": 1,
        "maxsize": 10,
        "timeout": 120,
        "distributions": {schema + ".soak_rows": {"type": "HASH", "field": "id"}},
    }
    await Tortoise.init(
        config={
            "connections": {
                "default": {"engine": "tortoise_gaussdb", "credentials": creds}
            },
            "apps": {"models": {"models": [module.__name__]}},
        }
    )
    db = Tortoise.get_connection("default")
    checks = 0

    async def batch(offset, size):
        nonlocal checks
        try:
            async with in_transaction():
                await SoakRow.bulk_create(
                    [SoakRow(id=offset + i, value=i) for i in range(size)],
                    batch_size=100,
                )
                assert (
                    await SoakRow.filter(id__gte=offset, id__lt=offset + size).count()
                    == size
                )
                await SoakRow.filter(id__gte=offset, id__lt=offset + size).update(
                    value=F("value") + 1
                )
                assert (await SoakRow.get(id=offset)).value == 1
                await SoakRow.filter(id__gte=offset, id__lt=offset + size).delete()
                if offset % 3 == 0:
                    raise ValueError("intentional rollback")
        except ValueError as exc:
            if str(exc) != "intentional rollback":
                raise
        checks += 1

    try:
        await Tortoise.generate_schemas()
        for concurrency in [1, 10, 50]:
            for size in [100, 1000]:
                # One warm-up, then three measured runs.
                await batch(1000000, size)
                durations = []
                for _ in range(3):
                    start = time.monotonic()
                    await asyncio.gather(
                        *(batch(i * 10000, size) for i in range(concurrency))
                    )
                    durations.append(round(time.monotonic() - start, 3))
                print(
                    json.dumps(
                        {
                            "target": tag,
                            "concurrency": concurrency,
                            "batch_size": size,
                            "seconds": durations,
                        }
                    ),
                    flush=True,
                )
        start = time.monotonic()
        last = start
        while time.monotonic() - start < seconds:
            await asyncio.gather(*(batch(i * 10000, 10) for i in range(10)))
            await asyncio.sleep(0.2)
            now = time.monotonic()
            if now - last >= 60:
                print(
                    json.dumps(
                        {
                            "target": tag,
                            "elapsed": round(now - start),
                            "completed_transactions": checks,
                        }
                    ),
                    flush=True,
                )
                last = now
        assert await SoakRow.all().count() == 0
        print(
            json.dumps(
                {
                    "target": tag,
                    "status": "PASS",
                    "soak_seconds": round(time.monotonic() - start, 2),
                    "completed_transactions": checks,
                }
            ),
            flush=True,
        )
    finally:
        await db.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await Tortoise.close_connections()


async def main(seconds):
    await asyncio.gather(target("CENTRAL", seconds), target("DIST", seconds))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    asyncio.run(main(args.seconds))
