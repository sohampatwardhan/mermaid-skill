"""Strict swimlane-beta target contract; a graph-family member (see reference/syntax/swimlanes.md)."""

from ..legacy_serializers import render_graph_swimlane
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['direction', 'nodes', 'groups', 'edges'])
SPEC = make_target_spec(
    'swimlane-beta', 'graph', LEGACY_FIELDS,
    legacy_serializer('graph', 'swimlane-beta', render_graph_swimlane),
)
