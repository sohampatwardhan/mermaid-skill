"""Strict ishikawa-beta target contract (see reference/syntax/ishikawa.md)."""

from ..legacy_serializers import render_ishikawa
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['problem', 'causes'])
SPEC = make_target_spec(
    'ishikawa-beta', 'ishikawa', LEGACY_FIELDS,
    legacy_serializer('ishikawa', 'ishikawa-beta', render_ishikawa),
    validator=lambda document: (),
)
