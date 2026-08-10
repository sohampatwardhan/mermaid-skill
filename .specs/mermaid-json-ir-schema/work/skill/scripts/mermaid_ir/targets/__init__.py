"""Production registration for the twelve independently owned Mermaid targets."""

from ..registry import TARGETS, register_target
from .architecture_beta import SPEC as architecture_beta
from .block import SPEC as block
from .c4_container import SPEC as c4_container
from .c4_context import SPEC as c4_context
from .class_diagram import SPEC as class_diagram
from .er_diagram import SPEC as er_diagram
from .flowchart import SPEC as flowchart
from .gantt import SPEC as gantt
from .mindmap import SPEC as mindmap
from .requirement_diagram import SPEC as requirement_diagram
from .sequence_diagram import SPEC as sequence_diagram
from .state_diagram_v2 import SPEC as state_diagram_v2

ALL_TARGETS = (flowchart, mindmap, block, c4_context, c4_container, architecture_beta,
               er_diagram, class_diagram, gantt, state_diagram_v2, sequence_diagram,
               requirement_diagram)


def register_all() -> None:
    """Idempotently populate the production registry without replacing contracts."""

    for spec in ALL_TARGETS:
        if spec.target not in TARGETS:
            register_target(spec)
