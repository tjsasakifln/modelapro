import pytest

from modules.results_generator import render_report
from tests.c08_report.fixtures import long_table_context, long_table_snapshot


@pytest.fixture(scope="module")
def long_table_pdf():
    """Shared synthetic long-table PDF (not client data)."""
    return render_report(long_table_snapshot(), long_table_context())
