#!/usr/bin/env python3
"""Preserve the proven flat-IR serializers behind the canonical compiler.

Target adapters translate canonical typed content into the former documented flat shape, then
call these pure functions. Keeping the compatibility implementation internal avoids a second
grammar rewrite while the public ``render.py`` becomes a versioned canonical facade.

The `--backend` flag defaults to (and today only supports) `mermaid`. It exists so a future
backend (e.g. TikZ) can add sibling serializer functions consuming the same IR files without
changing this dispatcher or any caller's JSON.

Families and their Mermaid targets:
  graph             -> flowchart, mindmap, block, C4Context, C4Container,
                       architecture-beta, erDiagram, classDiagram
                                                  (nodes/edges/groups; shared IR shape)
  timeline          -> gantt                     (sectioned bars, tags, milestones, excludes)
  state-machine     -> stateDiagram-v2            (states/transitions, composite, choice/fork/join)
  sequence          -> sequenceDiagram             (actors/steps: messages, activation, notes,
                                                     loop/opt/break/rect/alt/par/critical blocks)
  requirement-links -> requirementDiagram          (requirements/elements/links)

Schema details: ../reference/ir.md

Usage:
    scripts/render.py diagram.json
    scripts/render.py diagram.json --target flowchart -o diagram.mmd
    scripts/render.py diagram.json --backend mermaid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

IRError = ValueError


def _require(obj: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        raise IRError(f"{where} missing required field(s): {', '.join(missing)}")


def _safe_id(raw: str, table: dict[str, str]) -> str:
    """Map an arbitrary IR id to a Mermaid-safe bare identifier, memoized in `table`."""
    if raw in table:
        return table[raw]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        safe = raw
    else:
        safe = "n_" + re.sub(r"[^A-Za-z0-9_]", "_", raw)
        if not re.match(r"[A-Za-z_]", safe):
            safe = "n_" + safe
    # Disambiguate collisions created by sanitization (e.g. "1.1" and "1_1").
    base, suffix, candidate = safe, 0, safe
    while candidate in table.values():
        suffix += 1
        candidate = f"{base}_{suffix}"
    table[raw] = candidate
    return candidate


def _quote(text: Any) -> str:
    """Quote a label for Mermaid, escaping embedded quotes and flattening newlines."""
    value = str(text).replace("\r\n", " ").replace("\n", " ").replace('"', "#quot;")
    return f'"{value}"'


def _identifier(raw: str, where: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        raise IRError(f"{where} id {raw!r} must be a bare identifier (letters, digits, underscore)")
    return raw


_FLOWCHART_DIRECTIONS = {"TB", "TD", "BT", "LR", "RL"}
_CARDINAL_DIRECTIONS = {"TB", "BT", "LR", "RL"}


def _direction(
    ir: dict, where: str, *, allowed: set[str], default: str | None = None
) -> str | None:
    direction = ir.get("direction", default)
    if direction is not None and direction not in allowed:
        raise IRError(f"{where} has unknown direction {direction!r}; use one of {sorted(allowed)}")
    return direction


# --- graph family -----------------------------------------------------------------------

_FLOWCHART_SHAPES = {
    "terminator": "stadium",
    "process": "rect",
    "decision": "diamond",
    "io": "lean-r",
    "subprocess": "subproc",
    "document": "doc",
    "store": "cyl",
    "connector": "circle",
}
_FLOWCHART_EDGES = {
    "normal": "-->",
    "dependency": "-->",
    "conditional": "-.->",
    "weak": "-.->",
    "strong": "==>",
}
_MINDMAP_SHAPES = {
    "root": ("((", "))"),
    "circle": ("((", "))"),
    "square": ("[", "]"),
    "bang": ("))", "(("),
    "cloud": (")", "("),
}


def render_graph_flowchart(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/flowchart")
    ids: dict[str, str] = {}
    lines = [f"flowchart {_direction(ir, 'graph/flowchart', allowed=_FLOWCHART_DIRECTIONS, default='TD')}"]
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/flowchart node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        node_id = _safe_id(node["id"], ids)
        shape = _FLOWCHART_SHAPES.get(node.get("kind", "process"))
        if shape is None:
            raise IRError(f"graph/flowchart node {node['id']!r} has unknown kind {node['kind']!r}")
        lines.append(f'{indent}{node_id}@{{ shape: {shape}, label: {_quote(node["label"])} }}')

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/flowchart group")
        group_id = _safe_id(group["id"], ids)
        lines.append(f'  subgraph {group_id}[{_quote(group["label"])}]')
        for node in by_group.pop(group["id"], []):
            emit_node(node, "    ")
        lines.append("  end")
    for node in by_group.pop(None, []):
        emit_node(node, "  ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/flowchart nodes reference undeclared group(s): {leftover}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/flowchart edge")
        arrow = _FLOWCHART_EDGES.get(edge.get("kind", "normal"))
        if arrow is None:
            raise IRError(f"graph/flowchart edge has unknown kind {edge['kind']!r}")
        if edge["from"] not in ids or edge["to"] not in ids:
            raise IRError(f"graph/flowchart edge references undeclared node: {edge}")
        label = f'|{_quote(edge["label"])}|' if edge.get("label") else ""
        lines.append(f'  {ids[edge["from"]]} {arrow}{label} {ids[edge["to"]]}')
    return "\n".join(lines) + "\n"


_SWIMLANE_SHAPES = {
    "rect": ("[", "]"),
    "round": ("(", ")"),
    "stadium": ("([", "])"),
    "decision": ("{", "}"),
    "circle": ("((", "))"),
}
_SWIMLANE_EDGES = {
    "arrow": "-->",
    "line": "---",
    "dotted": "-.->",
    "thick": "==>",
}


def render_graph_swimlane(ir: dict) -> str:
    """swimlane-beta: lanes are top-level subgraphs; nodes/edges reuse flowchart-style syntax."""
    _require(ir, ("nodes", "edges"), "graph/swimlane")
    ids: dict[str, str] = {}
    lines = [f"swimlane-beta {_direction(ir, 'graph/swimlane', allowed=_FLOWCHART_DIRECTIONS, default='TB')}"]
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/swimlane node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        node_id = _safe_id(node["id"], ids)
        shape = _SWIMLANE_SHAPES.get(node.get("kind", "rect"))
        if shape is None:
            raise IRError(f"graph/swimlane node {node['id']!r} has unknown kind {node['kind']!r}")
        open_, close = shape
        lines.append(f'{indent}{node_id}{open_}{_quote(node["label"])}{close}')

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/swimlane group")
        group_id = _safe_id(group["id"], ids)
        lines.append(f'  subgraph {group_id} [{_quote(group["label"])}]')
        for node in by_group.pop(group["id"], []):
            emit_node(node, "    ")
        lines.append("  end")
    for node in by_group.pop(None, []):
        emit_node(node, "  ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/swimlane nodes reference undeclared group(s): {leftover}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/swimlane edge")
        arrow = _SWIMLANE_EDGES.get(edge.get("kind", "arrow"))
        if arrow is None:
            raise IRError(f"graph/swimlane edge has unknown kind {edge['kind']!r}")
        if edge["from"] not in ids or edge["to"] not in ids:
            raise IRError(f"graph/swimlane edge references undeclared node: {edge}")
        label = f'|{_quote(edge["label"])}|' if edge.get("label") else ""
        lines.append(f'  {ids[edge["from"]]} {arrow}{label} {ids[edge["to"]]}')
    return "\n".join(lines) + "\n"


def render_graph_mindmap(ir: dict) -> str:
    _require(ir, ("nodes", "edges", "root"), "graph/mindmap")
    nodes = {node["id"]: node for node in ir["nodes"]}
    if ir["root"] not in nodes:
        raise IRError(f"graph/mindmap root {ir['root']!r} is not a declared node")
    children: dict[str, list[str]] = {}
    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/mindmap edge")
        children.setdefault(edge["from"], []).append(edge["to"])

    lines = ["mindmap"]
    visited: set[str] = set()

    def emit(node_id: str, depth: int) -> None:
        if node_id in visited:
            raise IRError(f"graph/mindmap edges form a cycle at {node_id!r}; mindmap requires a tree")
        visited.add(node_id)
        node = nodes.get(node_id)
        if node is None:
            raise IRError(f"graph/mindmap edge references undeclared node {node_id!r}")
        kind = "root" if node_id == ir["root"] else node.get("kind", "default")
        if kind == "default":
            text = str(node["label"])
        else:
            open_, close = _MINDMAP_SHAPES.get(kind, ("", ""))
            if kind not in _MINDMAP_SHAPES:
                raise IRError(f"graph/mindmap node {node_id!r} has unknown kind {kind!r}")
            text = f'{open_}{node["label"]}{close}'
        lines.append("  " * (depth + 1) + text)
        for child in children.get(node_id, []):
            emit(child, depth + 1)

    emit(ir["root"], 0)
    return "\n".join(lines) + "\n"


_BLOCK_SHAPES = {
    "process": ("[", "]"),
    "terminator": ("([", "])"),
    "decision": ("{", "}"),
    "subprocess": ("[[", "]]"),
    "store": ("[(", ")]"),
    "connector": ("((", "))"),
    "io": ("[/", "/]"),
}


def render_graph_block(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/block")
    ids: dict[str, str] = {}
    lines = ["block"]
    columns = ir.get("columns")
    if columns is not None:
        if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
            raise IRError(f"graph/block 'columns' must be a positive integer, got {columns!r}")
        lines.append(f"  columns {columns}")
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/block node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        node_id = _safe_id(node["id"], ids)
        shape = _BLOCK_SHAPES.get(node.get("kind", "process"))
        if shape is None:
            raise IRError(f"graph/block node {node['id']!r} has unknown kind {node.get('kind')!r}")
        open_, close = shape
        lines.append(f"{indent}{node_id}{open_}{_quote(node['label'])}{close}")

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/block group")
        group_id = _safe_id(group["id"], ids)
        lines.append(f'  block:{group_id}[{_quote(group["label"])}]')
        for node in by_group.pop(group["id"], []):
            emit_node(node, "    ")
        lines.append("  end")
    for node in by_group.pop(None, []):
        emit_node(node, "  ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/block nodes reference undeclared group(s): {leftover}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/block edge")
        if edge["from"] not in ids or edge["to"] not in ids:
            raise IRError(f"graph/block edge references undeclared node/group: {edge}")
        if edge.get("label"):
            lines.append(f'  {ids[edge["from"]]}-- {_quote(edge["label"])} -->{ids[edge["to"]]}')
        else:
            lines.append(f'  {ids[edge["from"]]}-->{ids[edge["to"]]}')
    return "\n".join(lines) + "\n"


_C4_PERSON_SYSTEM_KINDS = {
    "person": "Person",
    "person_ext": "Person_Ext",
    "system": "System",
    "system_db": "SystemDb",
    "system_queue": "SystemQueue",
    "system_ext": "System_Ext",
    "system_db_ext": "SystemDb_Ext",
    "system_queue_ext": "SystemQueue_Ext",
}
_C4_CONTAINER_KINDS = {
    "container": "Container",
    "container_db": "ContainerDb",
    "container_queue": "ContainerQueue",
    "container_ext": "Container_Ext",
    "container_db_ext": "ContainerDb_Ext",
    "container_queue_ext": "ContainerQueue_Ext",
}
_C4_NODE_KINDS = {**_C4_PERSON_SYSTEM_KINDS, **_C4_CONTAINER_KINDS}
_C4_TARGET_NODE_KINDS = {
    "C4Context": set(_C4_PERSON_SYSTEM_KINDS),
    "C4Container": set(_C4_NODE_KINDS),
}
_C4_BOUNDARY_KINDS = {
    "enterprise_boundary": "Enterprise_Boundary",
    "system_boundary": "System_Boundary",
    "container_boundary": "Container_Boundary",
    "boundary": "Boundary",
}
_C4_TARGET_BOUNDARY_KINDS = {
    "C4Context": {"enterprise_boundary", "system_boundary", "boundary"},
    "C4Container": {"container_boundary", "boundary"},
}
_C4_REL_KINDS = {
    "rel": "Rel",
    "birel": "BiRel",
    "rel_up": "Rel_U",
    "rel_down": "Rel_D",
    "rel_left": "Rel_L",
    "rel_right": "Rel_R",
    "rel_back": "Rel_Back",
}


def render_graph_c4(ir: dict) -> str:
    target = ir.get("target")
    if target not in ("C4Context", "C4Container"):
        raise IRError(f"graph/c4 requires ir['target'] to be 'C4Context' or 'C4Container' (got {target!r})")
    _require(ir, ("nodes", "edges"), f"graph/{target}")
    allowed_node_kinds = _C4_TARGET_NODE_KINDS[target]
    allowed_boundary_kinds = _C4_TARGET_BOUNDARY_KINDS[target]
    lines = [target]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")

    known: set[str] = set()
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label", "kind"), f"graph/{target} node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        kind = node["kind"]
        macro = _C4_NODE_KINDS.get(kind)
        if macro is None or kind not in allowed_node_kinds:
            raise IRError(f"graph/{target} node {node['id']!r} has unknown/unsupported kind {kind!r}")
        node_id = _identifier(node["id"], f"graph/{target} node")
        known.add(node["id"])
        args = [node_id, _quote(node["label"])]
        technology = node.get("technology")
        description = node.get("description")
        if kind in _C4_CONTAINER_KINDS:
            if technology is not None:
                args.append(_quote(technology))
            elif description is not None:
                raise IRError(
                    f"graph/{target} node {node['id']!r} has 'description' but no 'technology'; "
                    "container macros take technology before description"
                )
        elif technology is not None:
            raise IRError(f"graph/{target} node {node['id']!r} kind {kind!r} does not accept 'technology'")
        if description is not None:
            args.append(_quote(description))
        lines.append(f'{indent}{macro}({", ".join(args)})')

    groups_by_id: dict[str, dict] = {}
    children_by_parent: dict[str | None, list[dict]] = {}
    for group in ir.get("groups", []):
        _require(group, ("id", "label", "kind"), f"graph/{target} group")
        if group["kind"] not in allowed_boundary_kinds:
            raise IRError(f"graph/{target} group {group['id']!r} has unknown/unsupported kind {group['kind']!r}")
        groups_by_id[group["id"]] = group
        children_by_parent.setdefault(group.get("group"), []).append(group)

    def emit_group(group: dict, indent: str) -> None:
        macro = _C4_BOUNDARY_KINDS[group["kind"]]
        group_id = _identifier(group["id"], f"graph/{target} group")
        args = [group_id, _quote(group["label"])]
        if group["kind"] == "boundary":
            if not group.get("boundary_type"):
                raise IRError(f"graph/{target} group {group['id']!r} of kind 'boundary' requires 'boundary_type'")
            args.append(_quote(group["boundary_type"]))
        elif group.get("boundary_type"):
            raise IRError(
                f"graph/{target} group {group['id']!r} kind {group['kind']!r} does not accept 'boundary_type'"
            )
        lines.append(f'{indent}{macro}({", ".join(args)}) {{')
        for node in by_group.pop(group["id"], []):
            emit_node(node, indent + "    ")
        for child in children_by_parent.pop(group["id"], []):
            emit_group(child, indent + "    ")
        lines.append(f"{indent}}}")

    for group in children_by_parent.pop(None, []):
        emit_group(group, "    ")
    leftover_groups = [g for g in children_by_parent if g is not None]
    if leftover_groups:
        raise IRError(f"graph/{target} groups reference undeclared parent group(s): {leftover_groups}")

    for node in by_group.pop(None, []):
        emit_node(node, "    ")
    leftover_nodes = [g for g in by_group if g is not None]
    if leftover_nodes:
        raise IRError(f"graph/{target} nodes reference undeclared group(s): {leftover_nodes}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to", "label"), f"graph/{target} edge")
        kind = edge.get("kind", "rel")
        macro = _C4_REL_KINDS.get(kind)
        if macro is None:
            raise IRError(f"graph/{target} edge has unknown kind {kind!r}")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"graph/{target} edge references undeclared node: {edge}")
        args = [edge["from"], edge["to"], _quote(edge["label"])]
        if edge.get("technology"):
            args.append(_quote(edge["technology"]))
        lines.append(f'    {macro}({", ".join(args)})')
    return "\n".join(lines) + "\n"


_ARCH_BASE_ICONS = {"cloud", "database", "disk", "internet", "server"}
_ARCH_SIDES = {"T", "B", "L", "R"}
_ARCH_ARROWS = {
    "none": ("", ""),
    "forward": ("", ">"),
    "backward": ("<", ""),
    "both": ("<", ">"),
}


def _arch_icon(icon: str, where: str) -> str:
    if icon in _ARCH_BASE_ICONS or ":" in icon:
        return icon
    raise IRError(
        f"{where} icon {icon!r} is not a built-in architecture icon {sorted(_ARCH_BASE_ICONS)}; "
        "use 'pack:icon-name' to reference a registered icon pack"
    )


def render_graph_architecture(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/architecture-beta")
    lines = ["architecture-beta"]
    known: set[str] = set()

    groups_by_id: dict[str, dict] = {}
    children_by_parent: dict[str | None, list[dict]] = {}
    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/architecture-beta group")
        groups_by_id[group["id"]] = group
        children_by_parent.setdefault(group.get("group"), []).append(group)

    def emit_group(group: dict) -> None:
        group_id = _identifier(group["id"], "graph/architecture-beta group")
        parent_id = group.get("group")
        parent = f" in {_identifier(parent_id, 'graph/architecture-beta group')}" if parent_id else ""
        icon = group.get("icon")
        where = f"graph/architecture-beta group {group['id']!r}"
        icon_part = f"({_arch_icon(icon, where)})" if icon else "()"
        lines.append(f'    group {group_id}{icon_part}[{_quote(group["label"])}]{parent}')
        for child in children_by_parent.pop(group["id"], []):
            emit_group(child)

    for group in children_by_parent.pop(None, []):
        emit_group(group)
    leftover_groups = [g for g in children_by_parent if g is not None]
    if leftover_groups:
        raise IRError(f"graph/architecture-beta groups reference undeclared parent group(s): {leftover_groups}")

    for node in ir["nodes"]:
        _require(node, ("id",), "graph/architecture-beta node")
        kind = node.get("kind", "service")
        node_id = _identifier(node["id"], "graph/architecture-beta node")
        group_ref = node.get("group")
        if group_ref is not None and group_ref not in groups_by_id:
            raise IRError(f"graph/architecture-beta node {node['id']!r} references undeclared group {group_ref!r}")
        parent = f" in {_identifier(group_ref, 'graph/architecture-beta node')}" if group_ref else ""
        if kind == "junction":
            if node.get("label") or node.get("icon"):
                raise IRError(f"graph/architecture-beta junction {node['id']!r} cannot have a label or icon")
            lines.append(f"    junction {node_id}{parent}")
        elif kind == "service":
            _require(node, ("label",), "graph/architecture-beta service node")
            icon = node.get("icon")
            where = f"graph/architecture-beta node {node['id']!r}"
            icon_part = f"({_arch_icon(icon, where)})" if icon else "()"
            lines.append(f'    service {node_id}{icon_part}[{_quote(node["label"])}]{parent}')
        else:
            raise IRError(f"graph/architecture-beta node {node['id']!r} has unknown kind {kind!r}")
        known.add(node["id"])

    for edge in ir["edges"]:
        _require(edge, ("from", "to", "from_side", "to_side"), "graph/architecture-beta edge")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"graph/architecture-beta edge references undeclared node: {edge}")
        if edge["from_side"] not in _ARCH_SIDES or edge["to_side"] not in _ARCH_SIDES:
            raise IRError(f"graph/architecture-beta edge has unknown side(s): {edge}")
        arrow_kind = edge.get("arrow", "none")
        arrow = _ARCH_ARROWS.get(arrow_kind)
        if arrow is None:
            raise IRError(f"graph/architecture-beta edge has unknown arrow kind {arrow_kind!r}")
        left_arrow, right_arrow = arrow
        from_suffix = "{group}" if edge.get("from_group") else ""
        to_suffix = "{group}" if edge.get("to_group") else ""
        lines.append(
            f'    {edge["from"]}{from_suffix}:{edge["from_side"]} {left_arrow}--{right_arrow} '
            f'{edge["to_side"]}:{edge["to"]}{to_suffix}'
        )
    return "\n".join(lines) + "\n"


_ER_LEFT_CARDINALITY = {"zero_or_one": "|o", "exactly_one": "||", "zero_or_more": "}o", "one_or_more": "}|"}
_ER_RIGHT_CARDINALITY = {"zero_or_one": "o|", "exactly_one": "||", "zero_or_more": "o{", "one_or_more": "|{"}


def _er_name(raw: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return raw
    return _quote(raw)


def render_graph_er(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/erDiagram")
    names: dict[str, str] = {}
    lines = ["erDiagram"]
    direction = _direction(ir, "graph/erDiagram", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    for node in ir["nodes"]:
        _require(node, ("id",), "graph/erDiagram node")
        bare = _er_name(node["id"])
        names[node["id"]] = bare
        header = f'{bare}[{_er_name(node["label"])}]' if node.get("label") else bare
        lines.append(f"    {header}")
        members = node.get("members", [])
        if members:
            lines.append(f"    {bare} {{")
            for member in members:
                lines.append(f"        {member}")
            lines.append("    }")
    for edge in ir["edges"]:
        _require(edge, ("from", "to", "label", "left", "right"), "graph/erDiagram edge")
        if edge["from"] not in names or edge["to"] not in names:
            raise IRError(f"graph/erDiagram edge references undeclared entity: {edge}")
        left = _ER_LEFT_CARDINALITY.get(edge["left"])
        right = _ER_RIGHT_CARDINALITY.get(edge["right"])
        if left is None:
            raise IRError(f"graph/erDiagram edge has unknown left cardinality {edge['left']!r}")
        if right is None:
            raise IRError(f"graph/erDiagram edge has unknown right cardinality {edge['right']!r}")
        identifying = edge.get("identifying", True)
        if not isinstance(identifying, bool):
            raise IRError(f"graph/erDiagram edge 'identifying' must be a boolean: {edge}")
        dash = "--" if identifying else ".."
        lines.append(
            f'    {names[edge["from"]]} {left}{dash}{right} {names[edge["to"]]} : {edge["label"]}'
        )
    return "\n".join(lines) + "\n"


_CLASS_ANNOTATIONS = {
    "interface": "Interface",
    "abstract": "Abstract",
    "service": "Service",
    "enumeration": "Enumeration",
}
_CLASS_EDGE_KINDS = {
    "inheritance": "<|--",
    "composition": "*--",
    "aggregation": "o--",
    "association": "-->",
    "link": "--",
    "dependency": "..>",
    "realization": "..|>",
    "link_dashed": "..",
}


def render_graph_class(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/classDiagram")
    names: dict[str, str] = {}
    lines = ["classDiagram"]
    direction = _direction(ir, "graph/classDiagram", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    for node in ir["nodes"]:
        _require(node, ("id",), "graph/classDiagram node")
        class_id = _identifier(node["id"], "graph/classDiagram node")
        names[node["id"]] = class_id
        kind = node.get("kind")
        annotation = None
        if kind is not None:
            annotation = _CLASS_ANNOTATIONS.get(kind)
            if annotation is None:
                raise IRError(f"graph/classDiagram node {node['id']!r} has unknown kind {kind!r}")
        header = f'{class_id}[{_quote(node["label"])}]' if node.get("label") else class_id
        members = node.get("members", [])
        if annotation or members:
            lines.append(f"    class {header} {{")
            if annotation:
                lines.append(f"        <<{annotation}>>")
            for member in members:
                lines.append(f"        {member}")
            lines.append("    }")
        else:
            lines.append(f"    class {header}")
    for edge in ir["edges"]:
        _require(edge, ("from", "to", "kind"), "graph/classDiagram edge")
        arrow = _CLASS_EDGE_KINDS.get(edge["kind"])
        if arrow is None:
            raise IRError(f"graph/classDiagram edge has unknown kind {edge['kind']!r}")
        if edge["from"] not in names or edge["to"] not in names:
            raise IRError(f"graph/classDiagram edge references undeclared class: {edge}")
        tokens = [names[edge["from"]]]
        if edge.get("from_card"):
            tokens.append(f'"{edge["from_card"]}"')
        tokens.append(arrow)
        if edge.get("to_card"):
            tokens.append(f'"{edge["to_card"]}"')
        tokens.append(names[edge["to"]])
        label = f' : {edge["label"]}' if edge.get("label") else ""
        lines.append(f"    {' '.join(tokens)}{label}")
    return "\n".join(lines) + "\n"


# --- timeline family ---------------------------------------------------------------------

_GANTT_TAGS = {"active", "done", "crit", "milestone"}


def _gantt_tags(bar: dict) -> list[str]:
    tags = bar.get("tags", [])
    unknown = [tag for tag in tags if tag not in _GANTT_TAGS]
    if unknown:
        raise IRError(f"timeline/gantt bar {bar['id']!r} has unknown tag(s) {unknown!r}")
    if len(set(tags)) != len(tags):
        raise IRError(f"timeline/gantt bar {bar['id']!r} repeats a tag: {tags!r}")
    if {"active", "done"}.issubset(tags):
        raise IRError(f"timeline/gantt bar {bar['id']!r} cannot be both active and done")
    if "milestone" in tags and ({"active", "done"} & set(tags)):
        raise IRError(f"timeline/gantt bar {bar['id']!r} cannot combine milestone with active/done")
    return list(tags)


def render_timeline_gantt(ir: dict) -> str:
    _require(ir, ("dateFormat", "sections"), "timeline/gantt")
    lines = ["gantt"]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")
    lines.append(f"    dateFormat {ir['dateFormat']}")
    if ir.get("axisFormat"):
        lines.append(f"    axisFormat {ir['axisFormat']}")
    for exclude in ir.get("excludes", []):
        lines.append(f"    excludes {exclude}")
    for section in ir["sections"]:
        _require(section, ("name", "bars"), "timeline/gantt section")
        lines.append(f"    section {section['name']}")
        for bar in section["bars"]:
            _require(bar, ("id", "label", "start", "end"), "timeline/gantt bar")
            bar_id = _identifier(bar["id"], "timeline/gantt bar")
            fields = _gantt_tags(bar) + [bar_id, bar["start"], bar["end"]]
            lines.append(f"    {bar['label']} :{', '.join(fields)}")
    return "\n".join(lines) + "\n"


# --- state-machine family -----------------------------------------------------------------

_STATE_PSEUDO_KINDS = {"choice", "fork", "join"}


def _emit_state_machine_body(ir: dict, lines: list[str], indent: str) -> None:
    """Emit one (possibly nested/composite) state machine's states/transitions/notes."""
    for state in ir.get("states", []):
        _require(state, ("id",), "state-machine state")
        kind = state.get("kind")
        if kind is not None and kind not in _STATE_PSEUDO_KINDS and "states" not in state:
            raise IRError(f"state-machine state {state['id']!r} has unknown kind {kind!r}")
        if kind in _STATE_PSEUDO_KINDS:
            lines.append(f'{indent}state {state["id"]} <<{kind}>>')
        elif "states" in state or "transitions" in state:
            lines.append(f'{indent}state {state["id"]} {{')
            _emit_state_machine_body(state, lines, indent + "    ")
            lines.append(f"{indent}}}")
        elif state.get("label"):
            lines.append(f'{indent}{state["id"]} : {state["label"]}')
    if ir.get("initial"):
        lines.append(f"{indent}[*] --> {ir['initial']}")
    for transition in ir.get("transitions", []):
        _require(transition, ("from", "to"), "state-machine transition")
        label = f' : {transition["label"]}' if transition.get("label") else ""
        lines.append(f'{indent}{transition["from"]} --> {transition["to"]}{label}')
    for final in ir.get("final", []):
        lines.append(f"{indent}{final} --> [*]")
    for note in ir.get("notes", []):
        _require(note, ("state", "side", "text"), "state-machine note")
        if note["side"] not in ("right", "left"):
            raise IRError(f"state-machine note on {note['state']!r} has unknown side {note['side']!r}")
        lines.append(f'{indent}note {note["side"]} of {note["state"]} : {note["text"]}')


def render_state_machine(ir: dict) -> str:
    _require(ir, ("transitions",), "state-machine")
    lines = ["stateDiagram-v2"]
    direction = _direction(ir, "state-machine", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    _emit_state_machine_body(ir, lines, "    ")
    return "\n".join(lines) + "\n"


# --- sequence family -----------------------------------------------------------------------

_SEQUENCE_ARROWS = {
    "sync": "->>",
    "async": "-)",
    "reply": "-->>",
    "cross": "-x",
}
_SEQUENCE_SINGLE_BODY_BLOCKS = {"loop", "opt", "break"}
_SEQUENCE_BRANCHED_BLOCKS = {
    "alt": ("alt", "else"),
    "par": ("par", "and"),
    "critical": ("critical", "option"),
}
_SEQUENCE_BREAK = "<br/>"


def _sequence_text(value: Any) -> str:
    # Mermaid treats semicolons as statement separators even inside message text.
    # Use its documented entity form so JSON text cannot terminate a statement.
    return str(value).replace(";", "#59;").replace("\r\n", _SEQUENCE_BREAK).replace("\n", _SEQUENCE_BREAK)


def _emit_sequence_steps(steps: list[dict], known: set[str], lines: list[str], indent: str) -> None:
    for step in steps:
        step_type = step.get("type", "message")
        if step_type == "message":
            _require(step, ("from", "to", "label"), "sequence message")
            if step["from"] not in known or step["to"] not in known:
                raise IRError(f"sequence message references an undeclared actor: {step}")
            arrow = _SEQUENCE_ARROWS.get(step.get("kind", "sync"))
            if arrow is None:
                raise IRError(f"sequence message has unknown kind {step['kind']!r}")
            lines.append(f'{indent}{step["from"]}{arrow}{step["to"]}: {_sequence_text(step["label"])}')
        elif step_type in ("activate", "deactivate"):
            _require(step, ("actor",), f"sequence {step_type}")
            if step["actor"] not in known:
                raise IRError(f"sequence {step_type} references an undeclared actor: {step}")
            lines.append(f'{indent}{step_type} {step["actor"]}')
        elif step_type == "note":
            _require(step, ("position", "actors", "text"), "sequence note")
            if step["position"] not in ("right_of", "left_of", "over"):
                raise IRError(f"sequence note has unknown position {step['position']!r}")
            unknown_actors = [actor for actor in step["actors"] if actor not in known]
            if unknown_actors:
                raise IRError(f"sequence note references undeclared actor(s): {unknown_actors}")
            side = step["position"].replace("_", " ")
            targets = ",".join(step["actors"])
            lines.append(f'{indent}Note {side} {targets}: {_sequence_text(step["text"])}')
        elif step_type in _SEQUENCE_SINGLE_BODY_BLOCKS:
            _require(step, ("label", "steps"), f"sequence {step_type} block")
            lines.append(f'{indent}{step_type} {step["label"]}')
            _emit_sequence_steps(step["steps"], known, lines, indent + "    ")
            lines.append(f"{indent}end")
        elif step_type == "rect":
            _require(step, ("color", "steps"), "sequence rect block")
            lines.append(f'{indent}rect {step["color"]}')
            _emit_sequence_steps(step["steps"], known, lines, indent + "    ")
            lines.append(f"{indent}end")
        elif step_type in _SEQUENCE_BRANCHED_BLOCKS:
            _require(step, ("branches",), f"sequence {step_type} block")
            if not step["branches"]:
                raise IRError(f"sequence {step_type} block must declare at least one branch")
            first_keyword, rest_keyword = _SEQUENCE_BRANCHED_BLOCKS[step_type]
            for index, branch in enumerate(step["branches"]):
                _require(branch, ("steps",), f"sequence {step_type} branch")
                keyword = first_keyword if index == 0 else rest_keyword
                label = f' {branch["label"]}' if branch.get("label") else ""
                lines.append(f"{indent}{keyword}{label}")
                _emit_sequence_steps(branch["steps"], known, lines, indent + "    ")
            lines.append(f"{indent}end")
        else:
            raise IRError(f"sequence step has unknown type {step_type!r}")


def render_sequence(ir: dict) -> str:
    _require(ir, ("actors", "steps"), "sequence")
    lines = ["sequenceDiagram"]
    known: set[str] = set()
    for actor in ir["actors"]:
        _require(actor, ("id",), "sequence actor")
        keyword = "actor" if actor.get("kind") == "actor" else "participant"
        lines.append(f'    {keyword} {actor["id"]}')
        known.add(actor["id"])
    _emit_sequence_steps(ir["steps"], known, lines, "    ")
    return "\n".join(lines) + "\n"


# --- requirement-links family --------------------------------------------------------------

_REQUIREMENT_TYPES = {
    "requirement", "functionalRequirement", "interfaceRequirement",
    "performanceRequirement", "physicalRequirement", "designConstraint",
}
_REQUIREMENT_RISKS = {"low", "medium", "high"}
_REQUIREMENT_METHODS = {"analysis", "inspection", "test", "demonstration"}
_REQUIREMENT_LINK_KINDS = {"contains", "copies", "derives", "satisfies", "verifies", "refines", "traces"}


def render_requirement_links(ir: dict) -> str:
    _require(ir, ("requirements", "elements", "links"), "requirement-links")
    lines = ["requirementDiagram"]
    direction = _direction(ir, "requirement-links", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    known = set()
    for requirement in ir["requirements"]:
        _require(requirement, ("id", "text"), "requirement-links requirement")
        rtype = requirement.get("type", "requirement")
        if rtype not in _REQUIREMENT_TYPES:
            raise IRError(f"requirement {requirement['id']!r} has unknown type {rtype!r}")
        risk = requirement.get("risk")
        if risk is not None and risk not in _REQUIREMENT_RISKS:
            raise IRError(f"requirement {requirement['id']!r} has unknown risk {risk!r}")
        method = requirement.get("verify_method")
        if method is not None and method not in _REQUIREMENT_METHODS:
            raise IRError(f"requirement {requirement['id']!r} has unknown verify_method {method!r}")
        req_id = _identifier(requirement["id"], "requirement-links requirement")
        lines.append(f"    {rtype} {req_id} {{")
        lines.append(f"        id: {requirement['id']}")
        lines.append(f"        text: {_quote(requirement['text'])}")
        if risk:
            lines.append(f"        risk: {risk}")
        if method:
            lines.append(f"        verifymethod: {method}")
        lines.append("    }")
        known.add(requirement["id"])
    for element in ir["elements"]:
        _require(element, ("id", "type"), "requirement-links element")
        elem_id = _identifier(element["id"], "requirement-links element")
        lines.append(f"    element {elem_id} {{")
        lines.append(f"        type: {element['type']}")
        if element.get("docref"):
            lines.append(f"        docref: {element['docref']}")
        lines.append("    }")
        known.add(element["id"])
    for link in ir["links"]:
        _require(link, ("from", "to", "kind"), "requirement-links link")
        if link["kind"] not in _REQUIREMENT_LINK_KINDS:
            raise IRError(f"requirement-links link has unknown kind {link['kind']!r}")
        if link["from"] not in known or link["to"] not in known:
            raise IRError(f"requirement-links link references an undeclared requirement/element: {link}")
        lines.append(f'    {link["from"]} - {link["kind"]} -> {link["to"]}')
    return "\n".join(lines) + "\n"


def _wardley_name(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", name) else _quote(name)


def _wardley_point(entry: dict) -> str:
    return f'[{entry["visibility"]}, {entry["evolution"]}]'


_WARDLEY_LINK_ARROWS = {
    "dependency": "->",
    "flow": "+>",
    "flowReverse": "+<",
    "flowBidirectional": "+<>",
}


def render_wardley(ir: dict) -> str:
    lines = ["wardley-beta"]
    if ir.get("size"):
        width, height = ir["size"]
        lines.append(f"size [{width}, {height}]")
    if ir.get("evolutionStages"):
        stages = []
        for stage in ir["evolutionStages"]:
            _require(stage, ("label",), "wardley evolutionStage")
            text = stage["label"] + (f'/{stage["dualLabel"]}' if stage.get("dualLabel") else "")
            if stage.get("width") is not None:
                text += f'@{stage["width"]}'
            stages.append(text)
        lines.append("evolution " + " -> ".join(stages))
    # Wardley's grammar has no separate id/label: a component's Name IS the token every other
    # statement (links, evolve, pipeline) references. This IR keeps a short internal `id` for
    # addressability, but every reference must resolve to the exact same rendered name as the
    # declaration, or the generated source would declare one token and reference another.
    names: dict[str, str] = {}
    for anchor in ir.get("anchors", []):
        _require(anchor, ("id", "visibility", "evolution"), "wardley anchor")
        names[anchor["id"]] = anchor.get("label", anchor["id"])
        lines.append(f'anchor {_wardley_name(names[anchor["id"]])} {_wardley_point(anchor)}')
    for component in ir.get("components", []):
        _require(component, ("id", "visibility", "evolution"), "wardley component")
        names[component["id"]] = component.get("label", component["id"])
        line = f'component {_wardley_name(names[component["id"]])} {_wardley_point(component)}'
        if component.get("labelOffset"):
            dx, dy = component["labelOffset"]
            line += f" label [{dx}, {dy}]"
        if component.get("sourcing"):
            line += f' ({component["sourcing"]})'
        if component.get("inertia"):
            line += " (inertia)"
        lines.append(line)
    for pipeline in ir.get("pipelines", []):
        _require(pipeline, ("parent", "stages"), "wardley pipeline")
        if pipeline["parent"] not in names:
            raise IRError(f"wardley pipeline references undeclared component {pipeline['parent']!r}")
        lines.append(f'pipeline {_wardley_name(names[pipeline["parent"]])} {{')
        for stage in pipeline["stages"]:
            _require(stage, ("label", "evolution"), "wardley pipeline stage")
            lines.append(f'  component {_quote(stage["label"])} [{stage["evolution"]}]')
        lines.append("}")
    for link in ir.get("links", []):
        _require(link, ("from", "to"), "wardley link")
        if link["from"] not in names or link["to"] not in names:
            raise IRError(f"wardley link references undeclared component/anchor: {link}")
        from_name, to_name = _wardley_name(names[link["from"]]), _wardley_name(names[link["to"]])
        kind = link.get("kind", "dependency")
        arrow = _WARDLEY_LINK_ARROWS.get(kind)
        if arrow is None:
            raise IRError(f"wardley link has unknown kind {kind!r}")
        if kind == "dependency":
            arrow = "-.->" if link.get("dashed") else "->"
            line = f'{from_name} {arrow} {to_name}'
            if link.get("label"):
                line += f'; {link["label"]}'
        elif kind == "flow" and link.get("label"):
            line = f'{from_name} +{_quote(link["label"])}> {to_name}'
        else:
            line = f'{from_name} {arrow} {to_name}'
        lines.append(line)
    for evolve in ir.get("evolve", []):
        _require(evolve, ("id", "target"), "wardley evolve")
        if evolve["id"] not in names:
            raise IRError(f"wardley evolve references undeclared component/anchor {evolve['id']!r}")
        lines.append(f'evolve {_wardley_name(names[evolve["id"]])} {evolve["target"]}')
    for note in ir.get("notes", []):
        _require(note, ("text", "visibility", "evolution"), "wardley note")
        lines.append(f'note {_quote(note["text"])} {_wardley_point(note)}')
    for accelerator in ir.get("accelerators", []):
        _require(accelerator, ("text", "visibility", "evolution"), "wardley accelerator")
        lines.append(f'accelerator {_quote(accelerator["text"])} {_wardley_point(accelerator)}')
    for deaccelerator in ir.get("deaccelerators", []):
        _require(deaccelerator, ("text", "visibility", "evolution"), "wardley deaccelerator")
        lines.append(f'deaccelerator {_quote(deaccelerator["text"])} {_wardley_point(deaccelerator)}')
    if ir.get("annotationsPosition"):
        lines.append(f'annotations {_wardley_point(ir["annotationsPosition"])}')
    for annotation in ir.get("annotations", []):
        _require(annotation, ("number", "visibility", "evolution", "text"), "wardley annotation")
        lines.append(f'annotation {annotation["number"]},{_wardley_point(annotation)} {_quote(annotation["text"])}')
    return "\n".join(lines) + "\n"


def _render_railroad_expr(expr: dict) -> str:
    kind = expr.get("kind")
    if kind == "terminal":
        _require(expr, ("text",), "railroad terminal")
        return f'terminal({_quote(expr["text"])})'
    if kind == "nonterminal":
        _require(expr, ("name",), "railroad nonterminal")
        return f'nonterminal({_quote(expr["name"])})'
    if kind == "special":
        _require(expr, ("text",), "railroad special")
        return f'special({_quote(expr["text"])})'
    if kind == "sequence":
        _require(expr, ("items",), "railroad sequence")
        return "sequence(" + ", ".join(_render_railroad_expr(item) for item in expr["items"]) + ")"
    if kind == "choice":
        _require(expr, ("items",), "railroad choice")
        return "choice(" + ", ".join(_render_railroad_expr(item) for item in expr["items"]) + ")"
    if kind == "optional":
        _require(expr, ("item",), "railroad optional")
        return f'optional({_render_railroad_expr(expr["item"])})'
    if kind == "zeroOrMore":
        _require(expr, ("item",), "railroad zeroOrMore")
        return f'zeroOrMore({_render_railroad_expr(expr["item"])})'
    if kind == "oneOrMore":
        _require(expr, ("item",), "railroad oneOrMore")
        return f'oneOrMore({_render_railroad_expr(expr["item"])})'
    raise IRError(f"railroad expression has unknown kind {kind!r}")


def render_railroad(ir: dict) -> str:
    _require(ir, ("rules",), "railroad")
    lines = ["railroad-beta"]
    for rule in ir["rules"]:
        _require(rule, ("name", "expression"), "railroad rule")
        lines.append(f'{rule["name"]} = {_render_railroad_expr(rule["expression"])} ;')
    return "\n".join(lines) + "\n"


def render_treeview(ir: dict) -> str:
    _require(ir, ("tree",), "treeView")
    lines = ["treeView-beta"]

    def emit(nodes: list, depth: int) -> None:
        for node in nodes:
            _require(node, ("label",), "treeView node")
            label = str(node["label"]) + ("/" if node.get("directory") else "")
            line = "    " * (depth + 1) + f'"{label}"'
            if node.get("description"):
                line += f' ## {node["description"]}'
            lines.append(line)
            emit(node.get("children", []), depth + 1)

    emit(ir["tree"], 0)
    return "\n".join(lines) + "\n"


def render_ishikawa(ir: dict) -> str:
    _require(ir, ("problem",), "ishikawa")
    lines = ["ishikawa-beta", f"    {ir['problem']}"]

    def emit(causes: list, depth: int) -> None:
        for cause in causes:
            _require(cause, ("label",), "ishikawa cause")
            lines.append("    " * (depth + 1) + cause["label"])
            emit(cause.get("causes", []), depth + 1)

    emit(ir.get("causes", []), 1)
    return "\n".join(lines) + "\n"


def _venn_label_size(entry: dict) -> str:
    suffix = f'[{_quote(entry["label"])}]' if entry.get("label") else ""
    if entry.get("size") is not None:
        suffix += f':{entry["size"]}'
    return suffix


def render_venn(ir: dict) -> str:
    _require(ir, ("sets",), "venn")
    lines = ["venn-beta"]
    known: set[str] = set()
    for entry in ir["sets"]:
        _require(entry, ("id",), "venn set")
        if entry["id"] in known:
            raise IRError(f"venn set {entry['id']!r} is declared more than once")
        known.add(entry["id"])
        lines.append(f'  set {entry["id"]}{_venn_label_size(entry)}')
        for text in entry.get("texts", []):
            _require(text, ("id", "label"), "venn text")
            lines.append(f'    text {text["id"]}[{_quote(text["label"])}]')
    for entry in ir.get("unions", []):
        _require(entry, ("ids",), "venn union")
        missing = [uid for uid in entry["ids"] if uid not in known]
        if missing:
            raise IRError(f"venn union references undeclared set(s): {missing}")
        lines.append(f'  union {",".join(entry["ids"])}{_venn_label_size(entry)}')
        for text in entry.get("texts", []):
            _require(text, ("id", "label"), "venn text")
            lines.append(f'    text {text["id"]}[{_quote(text["label"])}]')
    return "\n".join(lines) + "\n"


_EVENTMODELING_TYPES = {"ui", "pcr", "cmd", "rmo", "evt"}


def _render_data_field(field: dict) -> str:
    _require(field, ("key", "value"), "eventmodeling data field")
    value = field["value"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rendered = str(value)
    elif field.get("raw"):
        rendered = str(value)
    else:
        rendered = "'" + str(value).replace("'", "\\'") + "'"
    return f"{field['key']}: {rendered}"


def render_eventmodeling(ir: dict) -> str:
    _require(ir, ("timeframes",), "eventmodeling")
    lines = ["eventmodeling", ""]
    for frame in ir["timeframes"]:
        _require(frame, ("number", "type", "entity"), "eventmodeling timeframe")
        if frame["type"] not in _EVENTMODELING_TYPES:
            raise IRError(f"eventmodeling timeframe {frame['number']!r} has unknown type {frame['type']!r}")
        if frame.get("data") is not None and frame.get("dataRef") is not None:
            raise IRError(f"eventmodeling timeframe {frame['number']!r} sets both data and dataRef")
        token = "rf" if frame.get("reset") else "tf"
        line = f"{token} {frame['number']} {frame['type']} {frame['entity']}"
        if frame.get("relations"):
            line += "".join(f" ->> {number}" for number in frame["relations"])
        if frame.get("data") is not None:
            fields = "; ".join(_render_data_field(field) for field in frame["data"])
            prefix = f"`{frame['dataType']}`" if frame.get("dataType") else ""
            line += f" {prefix}{{ {fields} }}"
        elif frame.get("dataRef") is not None:
            line += f" [[{frame['dataRef']}]]"
        lines.append(line)
    for block in ir.get("dataBlocks", []):
        _require(block, ("id", "fields"), "eventmodeling data block")
        prefix = f"`{block['dataType']}`" if block.get("dataType") else ""
        lines.append("")
        lines.append(f"data {block['id']} {prefix}{{")
        for field in block["fields"]:
            lines.append(f"  {_render_data_field(field)}")
        lines.append("}")
    return "\n".join(lines) + "\n"


_CYNEFIN_DOMAINS = {"complex", "complicated", "clear", "chaotic", "confusion"}


def render_cynefin(ir: dict) -> str:
    lines = ["cynefin-beta"]
    seen: set[str] = set()
    for entry in ir.get("domains", []):
        _require(entry, ("domain",), "cynefin domain")
        domain = entry["domain"]
        if domain not in _CYNEFIN_DOMAINS:
            raise IRError(f"cynefin domain has unknown name {domain!r}")
        if domain in seen:
            raise IRError(f"cynefin domain {domain!r} is declared more than once")
        seen.add(domain)
        lines.append("")
        lines.append(f"  {domain}")
        for item in entry.get("items", []):
            lines.append(f"    {_quote(item)}")
    for transition in ir.get("transitions", []):
        _require(transition, ("from", "to"), "cynefin transition")
        if transition["from"] not in _CYNEFIN_DOMAINS or transition["to"] not in _CYNEFIN_DOMAINS:
            raise IRError(f"cynefin transition has an unknown domain: {transition}")
        lines.append("")
        label = f' : {_quote(transition["label"])}' if transition.get("label") else ""
        lines.append(f'  {transition["from"]} --> {transition["to"]}{label}')
    return "\n".join(lines) + "\n"


# --- dispatch ------------------------------------------------------------------------------

SERIALIZERS: dict[tuple[str, str], Callable[[dict], str]] = {
    ("graph", "flowchart"): render_graph_flowchart,
    ("graph", "mindmap"): render_graph_mindmap,
    ("graph", "block"): render_graph_block,
    ("graph", "C4Context"): render_graph_c4,
    ("graph", "C4Container"): render_graph_c4,
    ("graph", "architecture-beta"): render_graph_architecture,
    ("graph", "erDiagram"): render_graph_er,
    ("graph", "classDiagram"): render_graph_class,
    ("timeline", "gantt"): render_timeline_gantt,
    ("state-machine", "stateDiagram-v2"): render_state_machine,
    ("sequence", "sequenceDiagram"): render_sequence,
    ("requirement-links", "requirementDiagram"): render_requirement_links,
}


def render(ir: dict, target: str | None = None, backend: str = "mermaid") -> str:
    if backend != "mermaid":
        raise IRError(f"unsupported backend {backend!r}; only 'mermaid' is implemented today")
    _require(ir, ("diagram",), "IR document")
    family = ir["diagram"]
    resolved_target = target or ir.get("target")
    if not resolved_target:
        raise IRError("IR document has no 'target' and none was passed with --target")
    serializer = SERIALIZERS.get((family, resolved_target))
    if serializer is None:
        known = ", ".join(f"{f}->{t}" for f, t in SERIALIZERS)
        raise IRError(f"no serializer for {family}->{resolved_target}; known: {known}")
    return serializer(ir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ir_file", type=Path, help="Path to the diagram IR JSON file.")
    parser.add_argument("--target", default=None, help="Override the IR's 'target' field.")
    parser.add_argument("--backend", default="mermaid", choices=("mermaid",))
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write source here instead of stdout.")
    args = parser.parse_args(argv)

    try:
        ir = json.loads(args.ir_file.read_text(encoding="utf-8"))
        source = render(ir, target=args.target, backend=args.backend)
    except (IRError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(source, encoding="utf-8")
    else:
        print(source, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
