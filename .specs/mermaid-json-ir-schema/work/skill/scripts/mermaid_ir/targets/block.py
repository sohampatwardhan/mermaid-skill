"""Strict block target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_graph_block
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['columns', 'nodes', 'edges', 'groups'])
SPEC = make_target_spec(
    'block', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'block', render_graph_block),
)
