import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", help="Run GaussDB integration tests"
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        if any(
            name in item.path.parts for name in ("integration", "transport")
        ) and not config.getoption("--live"):
            item.add_marker(
                pytest.mark.skip(
                    reason="Use --live and configure dedicated test databases"
                )
            )
