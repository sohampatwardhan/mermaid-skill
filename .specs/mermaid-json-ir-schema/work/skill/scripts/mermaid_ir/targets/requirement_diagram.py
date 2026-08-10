"""Strict requirementDiagram target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_requirement_links
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['direction', 'requirements', 'elements', 'links'])
SPEC = make_target_spec(
    'requirementDiagram', 'requirement-links', LEGACY_FIELDS,
    legacy_serializer('requirement-links', 'requirementDiagram', render_requirement_links),
)
