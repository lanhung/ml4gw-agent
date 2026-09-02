import pytest

from ml4gw_agent.registry import load_default_registry


@pytest.fixture()
def registry():
    return load_default_registry()
