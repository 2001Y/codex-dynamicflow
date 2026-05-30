from __future__ import annotations

import ast
from typing import Any, List, Tuple


class MiniYAMLError(ValueError):
    pass


def load_minimal_yaml(text: str) -> Any:
    """Parse the small YAML subset used by codex-dynamicflow examples.

    This intentionally supports only dictionaries, lists, scalars, and inline
    Python/JSON-like literals. It avoids a PyYAML dependency so the MCP server
    can run from Hermes without extra packages.
    """
    lines: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        without_comment = _strip_comment(raw.rstrip())
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        lines.append((indent, without_comment.strip()))
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise MiniYAMLError(f"unexpected trailing YAML at line {index + 1}")
    return value


def _parse_block(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, current = lines[index]
    if current_indent < indent:
        return {}, index
    if current_indent != indent:
        raise MiniYAMLError(f"unexpected indentation at line {index + 1}")
    if current.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_dict(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[dict, int]:
    result = {}
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise MiniYAMLError(f"unexpected nested mapping at line {index + 1}")
        if text.startswith("- "):
            break
        key, value_text = _split_key_value(text, index)
        index += 1
        if value_text == "":
            if index < len(lines) and lines[index][0] > line_indent:
                value, index = _parse_block(lines, index, lines[index][0])
            else:
                value = {}
        else:
            value = _parse_scalar(value_text)
        result[key] = value
    return result, index


def _parse_list(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[list, int]:
    result = []
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not text.startswith("- "):
            break
        item_text = text[2:].strip()
        index += 1
        if item_text == "":
            if index < len(lines) and lines[index][0] > line_indent:
                item, index = _parse_block(lines, index, lines[index][0])
            else:
                item = None
        elif ":" in item_text and not item_text.startswith(('"', "'")):
            key, value_text = _split_key_value(item_text, index - 1)
            item = {}
            if value_text == "":
                if index < len(lines) and lines[index][0] > line_indent:
                    value, index = _parse_block(lines, index, lines[index][0])
                else:
                    value = {}
            else:
                value = _parse_scalar(value_text)
            item[key] = value
            while index < len(lines) and lines[index][0] > line_indent:
                extra_indent = lines[index][0]
                extra, index = _parse_dict(lines, index, extra_indent)
                item.update(extra)
        else:
            item = _parse_scalar(item_text)
        result.append(item)
    return result, index


def _split_key_value(text: str, index: int) -> Tuple[str, str]:
    if ":" not in text:
        raise MiniYAMLError(f"expected key: value at line {index + 1}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise MiniYAMLError(f"empty key at line {index + 1}")
    return key, value.strip()


def _parse_scalar(text: str) -> Any:
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            return ast.literal_eval(text)
        except Exception:
            if text.startswith("["):
                inner = text[1:-1].strip()
                if not inner:
                    return []
                return [part.strip().strip('"\'') for part in inner.split(",")]
            raise
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1].isspace():
                return line[:i].rstrip()
    return line
