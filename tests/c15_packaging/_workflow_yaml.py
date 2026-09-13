"""Minimal reader for .github/workflows/c15-ci.yml.

The structural CI guards need to see jobs, their shell defaults and their
steps. PyYAML is deliberately NOT used: it is not a declared dependency of
this project, C04 owns dependencies/constraints, and a meta-test about the
CI configuration should not be the thing that introduces a new package.

This is not a general YAML parser and must not become one. It understands
exactly the subset the workflow file uses: two-space indentation, block
mappings, ``|``/``>`` scalars, and ``- `` sequence items. Anything else it
does not claim to read.
"""

from __future__ import annotations

from typing import Any


def _scalar(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "~", ""}:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_block(lines: list[str], start: int, indent: int) -> tuple[Any, int]:
    """Parse the mapping or sequence at `indent`, returning (value, next_index)."""
    i = start
    mapping: dict[str, Any] = {}
    sequence: list[Any] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        cur = _indent(line)
        if cur < indent:
            break
        if cur > indent:
            # Content deeper than expected without a key: not our subset.
            i += 1
            continue
        body = line.strip()

        if body.startswith("- "):
            item_text = body[2:]
            if ":" in item_text and not item_text.startswith(("'", '"')):
                # A sequence item that is itself a mapping: re-read it as a
                # mapping whose first key sits on the dash line.
                rebuilt = [" " * (cur + 2) + item_text] + lines[i + 1:]
                value, consumed = _parse_block(rebuilt, 0, cur + 2)
                sequence.append(value)
                i = i + consumed
                continue
            sequence.append(_scalar(item_text))
            i += 1
            continue

        if ":" not in body:
            i += 1
            continue
        key, _, rest = body.partition(":")
        key = _scalar(key)
        rest = rest.strip()

        if rest in {"|", ">", "|-", ">-", "|+", ">+"}:
            block: list[str] = []
            i += 1
            inner = None
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and _indent(nxt) <= cur:
                    break
                if nxt.strip() and inner is None:
                    inner = _indent(nxt)
                block.append(nxt[inner:] if inner is not None and len(nxt) >= inner else nxt.strip())
                i += 1
            joiner = "\n" if rest.startswith("|") else " "
            mapping[key] = joiner.join(block)
            continue

        if rest:
            mapping[key] = _scalar(rest)
            i += 1
            continue

        value, i = _parse_block(lines, i + 1, cur + 2)
        mapping[key] = value

    if sequence and not mapping:
        return sequence, i
    return mapping, i


def load(text: str) -> dict:
    """Read the workflow file into nested dicts/lists."""
    lines = text.splitlines()
    value, _ = _parse_block(lines, 0, 0)
    return value if isinstance(value, dict) else {}
