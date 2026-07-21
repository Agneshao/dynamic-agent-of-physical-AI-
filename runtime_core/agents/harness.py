"""Version-bound synchronous harness for one logical agent role."""

from __future__ import annotations

from typing import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel

from runtime_core.schemas.agent_messages import AgentMessage
from runtime_core.schemas.agent_outputs import AgentContextView
from runtime_core.schemas.commands import Command
from runtime_core.schemas.organization import OrganizationState
from runtime_core.schemas.world_state import WorldSnapshot

from .lifecycle import AgentLifecycleStatus
from .role_profile import RoleProfile


class AgentHarnessError(RuntimeError):
    """Base error for logical agent admission and execution."""

    code = "AGENT_HARNESS_ERROR"


class AgentSuspendedError(AgentHarnessError):
    code = "AGENT_SUSPENDED"


class StaleAgentOrganizationVersionError(AgentHarnessError):
    code = "STALE_AGENT_ORGANIZATION_VERSION"


class AgentRoleInactiveError(AgentHarnessError):
    code = "AGENT_ROLE_INACTIVE"


class AgentModeNotAllowedError(AgentHarnessError):
    code = "AGENT_MODE_NOT_ALLOWED"


class AgentRecipientMismatchError(AgentHarnessError):
    code = "AGENT_RECIPIENT_MISMATCH"


class StaleAgentMessageOrganizationVersionError(AgentHarnessError):
    code = "STALE_AGENT_MESSAGE_ORGANIZATION_VERSION"


class StaleAgentMessageWorldVersionError(AgentHarnessError):
    code = "STALE_AGENT_MESSAGE_WORLD_VERSION"


class AgentMessageTypeNotAllowedError(AgentHarnessError):
    code = "AGENT_MESSAGE_TYPE_NOT_ALLOWED"


class AgentContextConfigurationError(AgentHarnessError):
    code = "AGENT_CONTEXT_CONFIGURATION_ERROR"


class AgentUnstructuredOutputError(AgentHarnessError):
    code = "AGENT_UNSTRUCTURED_OUTPUT"


class AgentForbiddenOutputError(AgentHarnessError):
    code = "AGENT_FORBIDDEN_OUTPUT"


AgentHandler = Callable[[AgentMessage, AgentContextView, tuple[object, ...]], object]


class AgentHarness:
    """Run one synchronous handler under lifecycle and version constraints."""

    def __init__(
        self,
        *,
        role_profile: RoleProfile,
        lifecycle_status: AgentLifecycleStatus,
        bound_org_version: int,
        agent_id: str,
        handler: AgentHandler,
        harness_id: UUID | None = None,
    ) -> None:
        if bound_org_version < 1:
            raise ValueError("bound_org_version must be at least 1")
        if not agent_id:
            raise ValueError("agent_id must not be empty")
        self.harness_id = harness_id or uuid4()
        self.role_profile = role_profile
        self.lifecycle_status = lifecycle_status
        self.bound_org_version = bound_org_version
        self.agent_id = agent_id
        self.handler = handler

    def handle(
        self,
        *,
        message: AgentMessage,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        dependencies: tuple[object, ...] = (),
    ) -> BaseModel:
        """Validate the binding and invoke the handler with a projected view."""
        if self.lifecycle_status != AgentLifecycleStatus.ACTIVE:
            raise AgentSuspendedError(self.agent_id)
        if organization.org_version != self.bound_org_version:
            raise StaleAgentOrganizationVersionError(
                f"harness org_version {self.bound_org_version} != "
                f"current {organization.org_version}"
            )
        if self.role_profile.role not in organization.active_roles:
            raise AgentRoleInactiveError(self.role_profile.role)
        if organization.mode not in self.role_profile.allowed_modes:
            raise AgentModeNotAllowedError(organization.mode.value)
        if message.recipient_role != self.role_profile.role:
            raise AgentRecipientMismatchError(message.recipient_role)
        if message.org_version != organization.org_version:
            raise StaleAgentMessageOrganizationVersionError(
                str(message.org_version)
            )
        if message.world_version != snapshot.world_version:
            raise StaleAgentMessageWorldVersionError(str(message.world_version))
        if message.message_type not in self.role_profile.allowed_input_types:
            raise AgentMessageTypeNotAllowedError(message.message_type.value)

        context = self._build_context(message, snapshot, organization)
        result = self.handler(message, context, dependencies)
        if isinstance(result, Command):
            raise AgentForbiddenOutputError("AgentHarness handlers cannot return Command")
        if not isinstance(result, BaseModel) or not result.model_config.get("frozen"):
            raise AgentUnstructuredOutputError(
                "AgentHarness handlers must return a frozen Pydantic model"
            )
        return result

    def _build_context(
        self,
        message: AgentMessage,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
    ) -> AgentContextView:
        supported_fields = {
            "people",
            "machines",
            "zones",
            "tasks",
            "routes",
            "weather",
            "new_tasks_frozen",
            "incident",
            "operator_target",
            "current_mode",
        }
        requested = self.role_profile.visible_context_fields
        unsupported = tuple(field for field in requested if field not in supported_fields)
        if unsupported:
            raise AgentContextConfigurationError(
                f"unsupported visible context fields: {unsupported}"
            )
        operator_field = message.get_payload("operator_target")
        operator_target = (
            str(operator_field.value) if operator_field is not None else None
        )
        state = snapshot.state
        return AgentContextView(
            visible_fields=requested,
            world_version=snapshot.world_version,
            org_version=organization.org_version,
            people=state.people if "people" in requested else None,
            machines=state.machines if "machines" in requested else None,
            zones=state.zones if "zones" in requested else None,
            tasks=state.tasks if "tasks" in requested else None,
            routes=state.routes if "routes" in requested else None,
            weather=state.weather if "weather" in requested else None,
            new_tasks_frozen=(
                state.new_tasks_frozen
                if "new_tasks_frozen" in requested
                else None
            ),
            incident_id=message.incident_id if "incident" in requested else None,
            operator_target=(
                operator_target if "operator_target" in requested else None
            ),
            current_mode=(
                organization.mode if "current_mode" in requested else None
            ),
        )
