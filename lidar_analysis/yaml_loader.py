from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, TextIO


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return ""

    low = value.lower()
    if low in {"null", "none", "~"}:
        return None
    if low == "true":
        return True
    if low == "false":
        return False

    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    if re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value)
        except Exception:
            pass

    if re.fullmatch(r"[+-]?(\d+\.\d*|\d*\.\d+)([eE][+-]?\d+)?", value) or re.fullmatch(
        r"[+-]?\d+[eE][+-]?\d+", value
    ):
        try:
            return float(value)
        except Exception:
            pass

    return value


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
    return line


def _simple_yaml_load(text: str) -> dict:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        clean = _strip_comment(raw_line).rstrip()
        if not clean.strip():
            continue

        indent = len(clean) - len(clean.lstrip(" "))
        content = clean.lstrip(" ")
        if ":" not in content:
            continue

        key, value_raw = content.split(":", 1)
        key = key.strip()
        value_raw = value_raw.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if value_raw == "":
            new_obj: dict[str, Any] = {}
            parent[key] = new_obj
            stack.append((indent, new_obj))
        else:
            parent[key] = _parse_scalar(value_raw)

    return root


def _simple_yaml_dump(data: Any, indent: int = 0) -> str:
    if not isinstance(data, dict):
        return f"{data!r}\n"

    lines: list[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_simple_yaml_dump(value, indent + 2).rstrip("\n"))
        elif isinstance(value, bool):
            lines.append(f"{pad}{key}: {'true' if value else 'false'}")
        elif value is None:
            lines.append(f"{pad}{key}: null")
        else:
            lines.append(f"{pad}{key}: {value}")
    return "\n".join(lines) + "\n"


@dataclass
class _YamlFallback:
    def safe_load(self, stream: str | TextIO) -> Any:
        text = stream.read() if hasattr(stream, "read") else str(stream)
        return _simple_yaml_load(text)

    def safe_dump(self, data: Any, stream: TextIO, sort_keys: bool = False) -> None:
        if isinstance(data, dict) and sort_keys:
            data = dict(sorted(data.items(), key=lambda kv: kv[0]))
        stream.write(_simple_yaml_dump(data))


try:
    import yaml as yaml  # type: ignore
except Exception:  # pragma: no cover - used in environments without PyYAML
    yaml = _YamlFallback()
