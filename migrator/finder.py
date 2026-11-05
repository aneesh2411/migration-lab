"""Locate usages of migrated symbols in a client repo via AST.

Import aliases are resolved (`import numpy as np` makes `np.float_`
match a rule about `numpy.float_`). Reports imports of moved packages,
call sites and plain attribute references to moved symbols, method
renames, and renamed keywords. Line/column data drives the patcher;
nothing is edited here.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Usage:
    path: Path
    symbol: str               # resolved dotted name or bare method name
    kind: str                 # import | call | attr_ref | method_call
    lineno: int
    kwargs: list[str] = field(default_factory=list)


def _dotted(node) -> str | None:
    """Resolve an Attribute/Name chain to a dotted string, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _alias_map(tree) -> dict[str, str]:
    """alias-or-name -> real top package, from plain import statements."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name] = a.name
    return out


def _resolve(dotted: str, aliases: dict[str, str]) -> str:
    head, _, rest = dotted.partition(".")
    real = aliases.get(head)
    return f"{real}.{rest}" if real and rest else (real or dotted)


def find_usages(repo: Path, rules) -> list[Usage]:
    old_funcs = {o.rsplit(".", 1)[-1] for o in rules.moves}
    kwarg_funcs = {f for (f, _o) in rules.kwarg_renames}
    usages: list[Usage] = []
    for path in sorted(Path(repo).rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        aliases = _alias_map(tree)
        seen_imports: set[int] = set()
        call_funcs = {id(n.func) for n in ast.walk(tree)
                      if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if any(a.name == o.rsplit(".", 1)[0]
                           for o in rules.moves):
                        if id(node) not in seen_imports:
                            usages.append(Usage(path, a.name, "import",
                                                node.lineno))
                            seen_imports.add(id(node))
            elif isinstance(node, ast.Call):
                dotted = _dotted(node.func)
                resolved = _resolve(dotted, aliases) if dotted else None
                kwargs = [k.arg for k in node.keywords if k.arg]
                if resolved in rules.moves:
                    usages.append(Usage(path, resolved, "call",
                                        node.lineno, kwargs))
                elif (isinstance(node.func, ast.Attribute)
                      and node.func.attr in rules.method_renames):
                    usages.append(Usage(path, node.func.attr,
                                        "method_call", node.lineno, kwargs))
                short = (resolved.rsplit(".", 1)[-1] if resolved
                         else node.func.attr
                         if isinstance(node.func, ast.Attribute) else "")
                if short in kwarg_funcs and any(
                        k in {o for (f, o) in rules.kwarg_renames if f == short}
                        for k in kwargs):
                    if not any(u.lineno == node.lineno and u.kind == "call"
                               for u in usages[-2:]):
                        usages.append(Usage(path, short, "call",
                                            node.lineno, kwargs))
            elif isinstance(node, ast.Attribute):
                if id(node) in call_funcs:
                    continue  # already reported as the call itself
                dotted = _dotted(node)
                if dotted:
                    resolved = _resolve(dotted, aliases)
                    if resolved in rules.moves:
                        usages.append(Usage(path, resolved, "attr_ref",
                                            node.lineno))
    return usages
