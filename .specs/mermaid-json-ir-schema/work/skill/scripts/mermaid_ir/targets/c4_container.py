"""Strict C4Container target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_c4
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['title', 'nodes', 'edges', 'groups'])
SPEC = make_target_spec(
    'C4Container', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'C4Container', render_graph_c4),
)
