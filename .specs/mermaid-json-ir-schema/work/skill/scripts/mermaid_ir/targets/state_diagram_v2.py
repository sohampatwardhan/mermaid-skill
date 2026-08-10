"""Strict stateDiagram-v2 target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_state_machine
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['direction', 'states', 'transitions', 'initial', 'final', 'notes'])
SPEC = make_target_spec(
    'stateDiagram-v2', 'state-machine', LEGACY_FIELDS,
    legacy_serializer('state-machine', 'stateDiagram-v2', render_state_machine),
)
