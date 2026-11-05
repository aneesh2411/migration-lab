"""Apply migration rules to client source with AST-precise edits.

Import aliases are resolved the same way as the finder, so a rule about
`numpy.float_` rewrites `np.float_` -> `np.float64` (alias kept), and a
from-import is rewritten as `from numpy import all as alltrue` so the
local binding and every call site stay valid. Every edit is an exact
AST span replacement applied to UTF-8 bytes (AST column offsets are
byte offsets, so non-ASCII source edits stay correct); the result must
re-parse or the whole patch is rejected - a broken half-edit is never
returned.
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


# Lines are UTF-8 *bytes*: AST col_offset/end_col_offset are UTF-8
# byte offsets, not Python character indexes. Editing str lines with
# them corrupts (or rejects) patches on any line containing non-ASCII
# text before the edit point.
def _span_replace(lines: list[bytes], node, new_text: str) -> None:
    nb = new_text.encode("utf-8")
    sl, sc = node.lineno - 1, node.col_offset
    el, ec = node.end_lineno - 1, node.end_col_offset
    if sl == el:
        lines[sl] = lines[sl][:sc] + nb + lines[sl][ec:]
    else:
        head, tail = lines[sl][:sc] + nb, lines[el][ec:]
        lines[sl:el + 1] = [head + tail]


def _name_replace(lines: list[bytes], node, old: str, new: str) -> None:
    """Replace only the leading identifier of a node's span."""
    ln, col = node.lineno - 1, node.col_offset
    ob = old.encode("utf-8")
    lines[ln] = (lines[ln][:col] + new.encode("utf-8")
                 + lines[ln][col + len(ob):])


def patch_file(path: Path, rules) -> PatchResult:
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    aliases = _alias_map(tree)
    # `import X as Y` bindings: after the import rewrite Y binds the
    # NEW package, unlike a bare `import X` where the top name still
    # binds the old package root
    asnames = {a.asname
               for n in ast.walk(tree) if isinstance(n, ast.Import)
               for a in n.names if a.asname}
    # bindings introduced by from-imports: the call-site edit for these
    # is the import rewrite below, so span edits skip them
    from_imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level \
                and node.module:
            for a in node.names:
                from_imports[a.asname or a.name] = \
                    f"{node.module}.{a.name}"
    lines = [l.encode("utf-8") for l in src.splitlines()]
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
        elif isinstance(node, ast.ImportFrom):
            # from M import old -> from M import new as old
            # The local binding is preserved, so call sites stay valid
            # and need no edit. A move that also changes the MODULE
            # (from textkit import slugify, slugify now in
            # textkit.text) is not rewritten here: it is left unedited
            # so evaluation fails honestly and escalates.
            if node.level or not node.module:
                continue
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if full not in rules.moves:
                    continue
                new_mod, new_tail = rules.moves[full].rsplit(".", 1)
                if new_mod != node.module:
                    edits.append(
                        f"unsupported: from-import module move {full} -> "
                        f"{rules.moves[full]} (left unedited)")
                    continue
                binding = alias.asname or alias.name
                if new_tail == binding:
                    continue
                replacement = (new_tail if alias.asname
                               else f"{new_tail} as {alias.name}")
                planned.append((alias.lineno, alias.col_offset,
                                "fromname", alias,
                                (alias.name, replacement)))
                edits.append(f"from {node.module} import {alias.name} -> "
                             f"{new_tail} (as {binding})")
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            resolved = _resolve(dotted, aliases) if dotted else None
            if resolved in rules.moves:
                head = dotted.split(".", 1)[0]
                pkg = rules.moves[resolved]
                if head in from_imports:
                    continue  # import rewrite keeps the binding valid
                # keep the surface alias; replace the resolved remainder
                imported = aliases.get(head, head)
                # an `as` alias binds whatever the (possibly rewritten)
                # import statement targets, so render against the NEW
                # package of that statement - otherwise
                # `import textkit as tk` + slugify moving to
                # textkit.text produces the bogus `tk.text.slugify`
                anchor = (pkg_moves.get(imported, imported)
                          if head in asnames else imported)
                rendered = head + pkg[len(anchor):]
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
            head = dotted.split(".", 1)[0]
            if (resolved in rules.moves and head not in from_imports
                    and not any(
                        p[3] is node or (p[0], p[1]) == (node.lineno,
                                                         node.col_offset)
                        for p in planned)):
                imported = aliases.get(head, head)
                anchor = (pkg_moves.get(imported, imported)
                          if head in asnames else imported)
                rendered = head + rules.moves[resolved][len(anchor):]
                planned.append((node.lineno, node.col_offset,
                                "span", node, rendered))
                edits.append(f"{dotted} -> {rendered}")

    for _ln, _c, kind, node, payload in sorted(
            planned, key=lambda p: (p[0], p[1]), reverse=True):
        if kind in ("kwname", "fromname"):
            _name_replace(lines, node, payload[0], payload[1])
        elif kind == "tail":
            # rename just the trailing attribute of a dotted call
            ln = node.end_lineno - 1
            ec = node.end_col_offset
            old_len = len(node.attr.encode("utf-8"))
            lines[ln] = (lines[ln][:ec - old_len]
                         + payload.encode("utf-8") + lines[ln][ec:])
        else:
            _span_replace(lines, node, payload)

    patched = "\n".join(l.decode("utf-8") for l in lines) \
        + ("\n" if src.endswith("\n") else "")
    try:
        ast.parse(patched)
    except SyntaxError:
        return PatchResult(Path(path), src, src, edits, ok=False)
    return PatchResult(Path(path), src, patched, edits, ok=True)
