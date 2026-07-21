"""Read-only observability UI for runtime snapshots and execution records."""

from .projection import ObservabilityView, build_observability_view

__all__ = ["ObservabilityView", "build_observability_view"]
