"""Rule-based authority arbitration for mower movement conflicts."""

from __future__ import annotations

from runtime_core.schemas.movement_authority import (
    AgentMovementPosition,
    MovementAuthorityDecision,
    MovementAuthorityRequest,
    MovementDecisionOutcome,
    MovementRecommendation,
)


class MovementAuthorityPolicy:
    """Let Supervisor publish the decision while preserving safety vetoes.

    Authority order is SAFETY_VETO > MAINTENANCE_CLEARANCE >
    OPERATIONS_CONTINUITY. Supervisor owns the final decision, Safety owns the
    safety veto, and Maintenance owns hazard clearance.
    """

    WINNING_RULE = "SAFETY_VETO>MAINTENANCE_CLEARANCE>OPERATIONS_CONTINUITY"

    def decide(self, request: MovementAuthorityRequest) -> MovementAuthorityDecision:
        positions = (
            AgentMovementPosition(
                role="operations",
                recommendation=MovementRecommendation.CONTINUE_MOWING,
                reason="Preserve the assigned mowing schedule and equipment utilization.",
            ),
            AgentMovementPosition(
                role="safety",
                recommendation=MovementRecommendation.STOP_MACHINE,
                reason="Water and unstable ground create traction and collision-control risk.",
                has_veto=True,
            ),
            AgentMovementPosition(
                role="maintenance",
                recommendation=MovementRecommendation.INSPECT_HAZARD,
                reason="The irrigation failure requires isolation and verified clearance.",
            ),
        )
        if request.hazard_active and request.route_affected:
            return MovementAuthorityDecision(
                device_id=request.device_id,
                outcome=MovementDecisionOutcome.HOLD_FOR_INSPECTION,
                final_authority="supervisor",
                positions=positions,
                winning_rule=self.WINNING_RULE,
                reason="Safety veto is active until Maintenance verifies the C-zone hazard is clear.",
            )
        return MovementAuthorityDecision(
            device_id=request.device_id,
            outcome=MovementDecisionOutcome.ALLOW,
            final_authority="supervisor",
            positions=positions,
            winning_rule="NO_ACTIVE_ROUTE_HAZARD",
            reason="The known hazard does not affect the proposed route.",
        )
