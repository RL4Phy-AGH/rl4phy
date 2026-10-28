import pytest

from test_client import fake_crossings


@pytest.fixture
def crossings() -> list:
    return fake_crossings(20, seed=1)
