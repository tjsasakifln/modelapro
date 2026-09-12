# Constraint lock

`linux-py3.txt` is a full `pip freeze` of a clean virtualenv after

```text
pip install ".[dev]"
```

on Linux with the Python version recorded in the file header.

## Update procedure

From a clone of this repository:

```text
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python -m c15_local.update_constraints
```

(`python -m c15_local.update_constraints` creates its own throwaway venv; do not hand-edit pins.)

Then run:

```text
pytest tests/c15_packaging/ -q
```

Direct runtime ranges live only in `pyproject.toml`. `requirements.txt` and `requirements-dev.txt` install the project with this lock and must not grow a second package list.

## Platforms

| OS | Lock used in CI | Notes |
| --- | --- | --- |
| Linux | `linux-py3.txt` | Generated and applied. |
| Windows | generated on the Windows candidate runner and retained with its evidence | The build uses a clean venv, checks the exact lock, inventories the MSYS2 UCRT64 Pango DLL closure and proves PDF output again from the installed frozen bundle. |
| macOS | untested | Declared, not assumed. |

Redis is `modelapro[redis]`, not part of the default lock application unless you install that extra.
