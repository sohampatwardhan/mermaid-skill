"""Strict sequenceDiagram target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_sequence
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['actors', 'steps'])
SPEC = make_target_spec(
    'sequenceDiagram', 'sequence', LEGACY_FIELDS,
    legacy_serializer('sequence', 'sequenceDiagram', render_sequence),
)
