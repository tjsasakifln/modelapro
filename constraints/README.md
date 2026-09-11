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
| Windows | same file if it resolves; otherwise unconstrained ranges | PDF native stack is **not** claimed; see WeasyPrint probe. |
| macOS | untested | Declared, not assumed. |

Redis is `modelapro[redis]`, not part of the default lock application unless you install that extra.
