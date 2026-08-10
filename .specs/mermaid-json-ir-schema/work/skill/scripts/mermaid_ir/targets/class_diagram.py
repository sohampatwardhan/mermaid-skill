"""Strict classDiagram target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_class
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['direction', 'nodes', 'edges'])
SPEC = make_target_spec(
    'classDiagram', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'classDiagram', render_graph_class),
)
