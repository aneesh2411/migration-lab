"""Apply migration rules to client source with AST-precise edits.

Import aliases are resolved the same way as the finder, so a rule about
`numpy.float_` rewrites `np.float_` -> `np.float64` (alias kept). Every
edit is an exact AST span replacement; the result must re-parse or the
whole patch is rejected - a broken half-edit is never returned.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .finder import _alias_map, _dotted, _resolve


@dataclass
class PatchResult:
    path: Path
    original: str
    patched: str
    edits: list[str] = field(default_factory=list)  # human-readable
    ok: bool = True


def _span_replace(lines: list[str], node, new_text: str) -> None:
    sl, sc = node.lineno - 1, node.col_offset
    el, ec = node.end_lineno - 1, node.end_col_offset
    if sl == el:
        lines[sl] = lines[sl][:sc] + new_text + lines[sl][ec:]
    else:
        head, tail = lines[sl][:sc] + new_text, lines[el][ec:]
        lines[sl:el + 1] = [head + tail]


def _name_replace(lines: list[str], node, old: str, new: str) -> None:
    """Replace only the leading identifier of a node's span."""
    ln, col = node.lineno - 1, node.col_offset
    lines[ln] = lines[ln][:col] + new + lines[ln][col + len(old):]


def patch_file(path: Path, rules) -> PatchResult:
    src = Path(path).read_text()
    tree = ast.parse(src, filename=str(path))
    aliases = _alias_map(tree)
    lines = src.splitlines()
    edits: list[str] = []
    planned = []  # (lineno, col, kind, node, payload)

    # import rewrites only when a move changes the package itself
    pkg_moves = {}
    for old, new in rules.moves.items():
        op, np_ = old.rsplit(".", 1)[0], new.rsplit(".", 1)[0]
        if op != np_:
            pkg_moves[op] = np_

    import_done: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if id(node) in import_done or alias.name not in pkg_moves:
                    continue
                seg = ast.get_source_segment(src, node)
                replacement = seg.replace(alias.name, pkg_moves[alias.name])
                planned.append((node.lineno, node.col_offset,
                                "span", node, replacement))
                edits.append(
                    f"import {alias.name} -> import {pkg_moves[alias.name]}")
                import_done.add(id(node))
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            resolved = _resolve(dotted, aliases) if dotted else None
            if resolved in rules.moves:
                head = dotted.split(".", 1)[0]
                pkg = rules.moves[resolved]
                # keep the surface alias; replace the resolved remainder
                imported = aliases.get(head, head)
                rendered = head + pkg[len(imported):]
                planned.append((node.func.lineno, node.func.col_offset,
                                "span", node.func, rendered))
                edits.append(f"{dotted} -> {rendered}")
            elif (isinstance(node.func, ast.Attribute)
                  and node.func.attr in rules.method_renames):
                new_name = rules.method_renames[node.func.attr]
                planned.append((node.func.lineno, node.func.end_col_offset,
                                "tail", node.func, new_name))
                edits.append(f".{node.func.attr}(...) -> .{new_name}(...)")
            short = (resolved.rsplit(".", 1)[-1] if resolved else "")
            for kw in node.keywords:
                if kw.arg and (short, kw.arg) in rules.kwarg_renames:
                    new_name = rules.kwarg_renames[(short, kw.arg)]
                    planned.append((kw.lineno, kw.col_offset,
                                    "kwname", kw, (kw.arg, new_name)))
                    edits.append(f"kwarg {short}({kw.arg}=) -> {new_name}=")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if not dotted:
                continue
            resolved = _resolve(dotted, aliases)
            if resolved in rules.moves and not any(
                    p[3] is node or (p[0], p[1]) == (node.lineno,
                                                     node.col_offset)
                    for p in planned):
                head = dotted.split(".", 1)[0]
                imported = aliases.get(head, head)
                rendered = head + rules.moves[resolved][len(imported):]
                planned.append((node.lineno, node.col_offset,
                                "span", node, rendered))
                edits.append(f"{dotted} -> {rendered}")

    for _ln, _c, kind, node, payload in sorted(
            planned, key=lambda p: (p[0], p[1]), reverse=True):
        if kind == "kwname":
            _name_replace(lines, node, payload[0], payload[1])
        elif kind == "tail":
            # rename just the trailing attribute of a dotted call
            ln = node.end_lineno - 1
            ec = node.end_col_offset
            old_len = len(node.attr)
            lines[ln] = (lines[ln][:ec - old_len] + payload
                         + lines[ln][ec:])
        else:
            _span_replace(lines, node, payload)

    patched = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
    try:
        ast.parse(patched)
    except SyntaxError:
        return PatchResult(Path(path), src, src, edits, ok=False)
    return PatchResult(Path(path), src, patched, edits, ok=True)
