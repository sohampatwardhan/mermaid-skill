"""Production registration for the Mermaid targets this skill can generate."""

from ..registry import TARGETS, register_target
from .architecture_beta import SPEC as architecture_beta
from .block import SPEC as block
from .c4_container import SPEC as c4_container
from .c4_context import SPEC as c4_context
from .class_diagram import SPEC as class_diagram
from .cynefin_beta import SPEC as cynefin_beta
from .er_diagram import SPEC as er_diagram
from .eventmodeling import SPEC as eventmodeling
from .flowchart import SPEC as flowchart
from .gantt import SPEC as gantt
from .ishikawa_beta import SPEC as ishikawa_beta
from .mindmap import SPEC as mindmap
from .railroad_beta import SPEC as railroad_beta
from .requirement_diagram import SPEC as requirement_diagram
from .sequence_diagram import SPEC as sequence_diagram
from .state_diagram_v2 import SPEC as state_diagram_v2
from .swimlane_beta import SPEC as swimlane_beta
from .treeview_beta import SPEC as treeview_beta
from .venn_beta import SPEC as venn_beta
from .wardley_beta import SPEC as wardley_beta

# The first 12 went through the full inventory/coverage audit against a pinned Mermaid source
# snapshot (see .specs/mermaid-json-ir-schema); later additions are functionally complete and
# fully tested but are not (yet) run through that same construct-by-construct audit trail.
ALL_TARGETS = (flowchart, mindmap, block, c4_context, c4_container, architecture_beta,
               er_diagram, class_diagram, gantt, state_diagram_v2, sequence_diagram,
               requirement_diagram, swimlane_beta, cynefin_beta, eventmodeling, venn_beta,
               ishikawa_beta, treeview_beta, railroad_beta, wardley_beta)


def register_all() -> None:
    """Idempotently populate the production registry without replacing contracts."""

    for spec in ALL_TARGETS:
        if spec.target not in TARGETS:
            register_target(spec)
