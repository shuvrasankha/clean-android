"""Strict parser for the small YAML subset used by data/packages/*.yaml.

Runtime dependencies are Typer and Rich only, so PyYAML is not used here. Supported: a top-level
list of flat mappings; scalars (plain, 'single' or "double" quoted, true/false, integers); lists as
`[a, "b"]` or as indented `- item` lines; `#` comments. Anything else is an error, never a guess.
"""

from __future__ import annotations

import re

Scalar = str | bool | int
Value = Scalar | list[Scalar]

_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_INT_RE = re.compile(r"^-?\d+$")


class YamlSubsetError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _scalar(text: str) -> Scalar:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if text[0] == '"' else inner
    if text in ("true", "false"):
        return text == "true"
    if _INT_RE.match(text):
        return int(text)
    return text


def _split_inline(body: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in body:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote:
        raise YamlSubsetError("unterminated quote in list")
    tail = "".join(buf)
    if tail.strip() or parts:
        parts.append(tail)
    return [p for p in parts if p.strip()]


def parse_entries(text: str) -> list[dict[str, Value]]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    entries: list[dict[str, Value]] = []
    current: dict[str, Value] | None = None
    list_key: str | None = None

    for n, raw in enumerate(text.split("\n"), start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise YamlSubsetError(f"line {n}: tabs are not allowed for indentation")
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()

        if indent == 0:
            if not body.startswith("- "):
                raise YamlSubsetError(f"line {n}: expected '- ' to start an entry")
            current = {}
            entries.append(current)
            list_key = None
            body = body[2:].strip()
        elif current is None:
            raise YamlSubsetError(f"line {n}: indented line before any entry")
        elif body.startswith("- "):
            if indent <= 2 or list_key is None:
                raise YamlSubsetError(f"line {n}: unexpected list item")
            items = current[list_key]
            assert isinstance(items, list)
            items.append(_scalar(body[2:]))
            continue
        elif indent != 2:
            raise YamlSubsetError(f"line {n}: keys must be indented by exactly 2 spaces")

        key, sep, value = body.partition(":")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            raise YamlSubsetError(f"line {n}: expected 'key: value', got {body!r}")
        if key in current:
            raise YamlSubsetError(f"line {n}: duplicate key {key!r}")
        value = value.strip()
        list_key = None
        if not value:
            current[key] = []
            list_key = key
        elif value.startswith("["):
            if not value.endswith("]"):
                raise YamlSubsetError(f"line {n}: unterminated inline list")
            current[key] = [_scalar(p) for p in _split_inline(value[1:-1])]
        else:
            current[key] = _scalar(value)
    return entries
