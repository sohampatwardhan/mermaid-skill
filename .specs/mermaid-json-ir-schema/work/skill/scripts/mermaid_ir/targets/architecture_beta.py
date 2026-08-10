"""Strict architecture-beta target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_architecture
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['nodes', 'edges', 'groups'])
SPEC = make_target_spec(
    'architecture-beta', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'architecture-beta', render_graph_architecture),
)
