"""Strict gantt target contract; required fields are schema-declared and optional fields are explicit."""

from ..legacy_serializers import render_timeline_gantt
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['title', 'dateFormat', 'axisFormat', 'excludes', 'sections'])
SPEC = make_target_spec(
    'gantt', 'timeline', LEGACY_FIELDS,
    legacy_serializer('timeline', 'gantt', render_timeline_gantt),
)
