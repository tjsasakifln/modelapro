import pytest

from backend.api import reset_runtime


@pytest.fixture(autouse=True)
def _isolate_runtime():
    reset_runtime()
    yield
    reset_runtime()
