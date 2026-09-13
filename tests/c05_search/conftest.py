"""C05 test fixtures."""
import pytest

from modules.optimal_combination import clear_search_cache


@pytest.fixture(autouse=True)
def _isolate_search_cache():
    clear_search_cache()
    yield
    clear_search_cache()
