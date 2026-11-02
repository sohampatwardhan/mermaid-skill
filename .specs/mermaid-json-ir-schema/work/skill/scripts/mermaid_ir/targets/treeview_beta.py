"""Strict treeView-beta target contract (see reference/syntax/treeView.md)."""

from ..legacy_serializers import render_treeview
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['tree'])
SPEC = make_target_spec(
    'treeView-beta', 'treeView', LEGACY_FIELDS,
    legacy_serializer('treeView', 'treeView-beta', render_treeview),
    validator=lambda document: (),
)
