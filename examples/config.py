import os


def make_config():
    schema = os.getenv("GAUSS_SCHEMA", "gaussdb_demo")
    return {
        "connections": {
            "default": {
                "engine": "tortoise_gaussdb",
                "credentials": {
                    "host": os.environ["GAUSS_HOST"],
                    "port": int(os.environ["GAUSS_PORT"]),
                    "database": os.environ["GAUSS_DATABASE"],
                    "user": os.environ["GAUSS_USER"],
                    "password": os.environ["GAUSS_PASSWORD"],
                    "schema": schema,
                    "deployment": os.environ["GAUSS_DEPLOYMENT"],
                    "distributions": {
                        f"{schema}.orders": {"type": "HASH", "field": "id"}
                    },
                    "minsize": 1,
                    "maxsize": 5,
                },
            }
        },
        "apps": {
            "models": {
                "models": ["examples.models"],
                "default_connection": "default",
                "migrations": "examples.migrations",
            }
        },
        "use_tz": True,
        "timezone": "UTC",
    }


# For tortoise -c examples.config.CONFIG init/makemigrations.
CONFIG = make_config()
