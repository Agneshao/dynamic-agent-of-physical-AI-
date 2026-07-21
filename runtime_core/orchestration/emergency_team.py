"""Fixed synchronous orchestration for the minimal emergency team."""

from __future__ import annotations

from uuid import UUID, uuid4

from runtime_core.agents.emergency_agents import (
    communication_handler,
    incident_commander_handler,
    operations_handler,
    safety_handler,
)
from runtime_core.agents.harness import AgentHarness
from runtime_core.agents.lifecycle import AgentLifecycleStatus
from runtime_core.agents.role_profile import emergency_role_profiles
from runtime_core.organization.minimal_org_selector import MinimalOrganizationPlan
from runtime_core.schemas.agent_messages import (
    AgentMessage,
    AgentMessageType,
    AgentPayloadField,
)
from runtime_core.schemas.agent_outputs import (
    AgentInteractionRecord,
    EmergencyTeamResult,
    NotificationPlan,
    OperationsPlan,
    SafetyReport,
)
from runtime_core.schemas.organization import OperatingMode, OrganizationState
from runtime_core.schemas.proposals import Proposal
from runtime_core.schemas.world_state import WorldSnapshot


class EmergencyTeamOrchestrator:
    """Coordinate messages and return a Proposal without touching runtime writers."""

    def run(
        self,
        *,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        plan: MinimalOrganizationPlan,
    ) -> EmergencyTeamResult:
        if organization.mode != OperatingMode.EMERGENCY:
            raise ValueError("emergency team requires EMERGENCY mode")
        required_roles = {
            "incident_commander",
            "safety",
            "operations",
            "communication",
        }
        if not required_roles.issubset(set(organization.active_roles)):
            raise ValueError("emergency organization is missing required active roles")

        profiles = {profile.role: profile for profile in emergency_role_profiles()}
        handlers = {
            "incident_commander": incident_commander_handler,
            "safety": safety_handler,
            "operations": operations_handler,
            "communication": communication_handler,
        }
        harnesses = {
            role: AgentHarness(
                role_profile=profiles[role],
                lifecycle_status=AgentLifecycleStatus.ACTIVE,
                bound_org_version=organization.org_version,
                agent_id=f"{role}:{organization.org_version}",
                handler=handler,
            )
            for role, handler in handlers.items()
        }
        correlation_id = uuid4()
        interactions: list[AgentInteractionRecord] = []

        safety_task = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.TASK_ASSIGNMENT,
            sender="incident_commander",
            recipient="safety",
            snapshot=snapshot,
            organization=organization,
            objective="Assess immediate human and machine exposure.",
        )
        safety_report = harnesses["safety"].handle(
            message=safety_task,
            snapshot=snapshot,
            organization=organization,
        )
        assert isinstance(safety_report, SafetyReport)
        interactions.append(self._record(1, safety_task, safety_report.risk_summary))
        safety_response = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.SAFETY_REPORT,
            sender="safety",
            recipient="incident_commander",
            snapshot=snapshot,
            organization=organization,
            objective="Return structured exposure evidence.",
            payload=(
                AgentPayloadField(name="required_holds", value=safety_report.required_holds),
                AgentPayloadField(name="confidence", value=safety_report.confidence),
            ),
        )
        interactions.append(self._record(2, safety_response, safety_report.risk_summary))

        operations_task = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.TASK_ASSIGNMENT,
            sender="incident_commander",
            recipient="operations",
            snapshot=snapshot,
            organization=organization,
            objective="Produce bounded equipment actions from safety evidence.",
        )
        operations_plan = harnesses["operations"].handle(
            message=operations_task,
            snapshot=snapshot,
            organization=organization,
            dependencies=(safety_report,),
        )
        assert isinstance(operations_plan, OperationsPlan)
        interactions.append(
            self._record(3, operations_task, operations_plan.operational_summary)
        )
        operations_response = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.OPERATIONS_PLAN,
            sender="operations",
            recipient="incident_commander",
            snapshot=snapshot,
            organization=organization,
            objective="Return equipment action recommendations.",
            payload=(
                AgentPayloadField(
                    name="actions",
                    value=tuple(
                        action.action_type
                        for action in operations_plan.recommended_actions
                    ),
                ),
                AgentPayloadField(name="confidence", value=operations_plan.confidence),
            ),
        )
        interactions.append(
            self._record(4, operations_response, operations_plan.operational_summary)
        )

        communication_task = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.TASK_ASSIGNMENT,
            sender="incident_commander",
            recipient="communication",
            snapshot=snapshot,
            organization=organization,
            objective="Prepare an operator notification plan.",
            payload=(AgentPayloadField(name="operator_target", value="operator_1"),),
        )
        notification_plan = harnesses["communication"].handle(
            message=communication_task,
            snapshot=snapshot,
            organization=organization,
        )
        assert isinstance(notification_plan, NotificationPlan)
        interactions.append(
            self._record(5, communication_task, notification_plan.notification_summary)
        )
        notification_response = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.NOTIFICATION_PLAN,
            sender="communication",
            recipient="incident_commander",
            snapshot=snapshot,
            organization=organization,
            objective="Return notification recipients and category.",
            payload=(
                AgentPayloadField(name="recipients", value=notification_plan.recipients),
                AgentPayloadField(name="category", value=notification_plan.message_category),
            ),
        )
        interactions.append(
            self._record(6, notification_response, notification_plan.notification_summary)
        )

        proposal = harnesses["incident_commander"].handle(
            message=notification_response,
            snapshot=snapshot,
            organization=organization,
            dependencies=(safety_report, operations_plan, notification_plan),
        )
        assert isinstance(proposal, Proposal)
        final_message = self._message(
            correlation_id=correlation_id,
            incident_id=plan.incident_id,
            message_type=AgentMessageType.FINAL_PROPOSAL,
            sender="incident_commander",
            recipient="proposal_board",
            snapshot=snapshot,
            organization=organization,
            objective="Submit the composed emergency response for admission.",
            payload=(
                AgentPayloadField(name="proposal_id", value=str(proposal.proposal_id)),
                AgentPayloadField(name="action_count", value=len(proposal.actions)),
            ),
        )
        interactions.append(self._record(7, final_message, proposal.rationale_summary))
        return EmergencyTeamResult(
            incident_id=plan.incident_id,
            selected_roles=plan.selected_roles,
            interactions=tuple(interactions),
            safety_report=safety_report,
            operations_plan=operations_plan,
            notification_plan=notification_plan,
            proposal=proposal,
        )

    @staticmethod
    def _message(
        *,
        correlation_id: UUID,
        incident_id: str,
        message_type: AgentMessageType,
        sender: str,
        recipient: str,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        objective: str,
        payload: tuple[AgentPayloadField, ...] = (),
    ) -> AgentMessage:
        return AgentMessage(
            correlation_id=correlation_id,
            incident_id=incident_id,
            message_type=message_type,
            sender_role=sender,
            recipient_role=recipient,
            world_version=snapshot.world_version,
            org_version=organization.org_version,
            objective=objective,
            payload=payload,
            created_at=snapshot.created_at,
        )

    @staticmethod
    def _record(
        sequence: int,
        message: AgentMessage,
        output_summary: str,
    ) -> AgentInteractionRecord:
        return AgentInteractionRecord(
            sequence=sequence,
            message_id=message.message_id,
            correlation_id=message.correlation_id,
            incident_id=message.incident_id,
            sender_role=message.sender_role,
            recipient_role=message.recipient_role,
            message_type=message.message_type,
            world_version=message.world_version,
            org_version=message.org_version,
            objective=message.objective,
            payload=message.payload,
            output_type=message.message_type.value,
            output_summary=output_summary,
            created_at=message.created_at,
        )
