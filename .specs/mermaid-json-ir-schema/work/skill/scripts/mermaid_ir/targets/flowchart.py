"""Strict flowchart target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_flowchart
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['direction', 'nodes', 'edges', 'groups'])
SPEC = make_target_spec(
    'flowchart', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'flowchart', render_graph_flowchart),
)
