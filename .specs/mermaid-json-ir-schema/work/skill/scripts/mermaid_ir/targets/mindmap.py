"""Strict mindmap target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_mindmap
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['root', 'nodes', 'edges'])
SPEC = make_target_spec(
    'mindmap', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'mindmap', render_graph_mindmap),
)
