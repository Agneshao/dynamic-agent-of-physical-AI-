"""Immutable structured evidence emitted by command execution."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .world_state import utc_now


class EvidenceKind(str, Enum):
    """Sources of evidence in the minimal execution pipeline."""

    ADAPTER_EXECUTION = "ADAPTER_EXECUTION"
    ADAPTER_VERIFICATION = "ADAPTER_VERIFICATION"
    KERNEL_SYNC = "KERNEL_SYNC"
    KERNEL_SYNC_FAILED = "KERNEL_SYNC_FAILED"


EvidenceScalar = Union[str, int, float, bool, None]
EvidenceValue = Union[EvidenceScalar, tuple[EvidenceScalar, ...]]


class EvidenceFact(BaseModel):
    """One immutable JSON-safe evidence value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: EvidenceValue

    @field_validator("value")
    @classmethod
    def reject_non_finite_numbers(cls, value: EvidenceValue) -> EvidenceValue:
        values = value if isinstance(value, tuple) else (value,)
        if any(isinstance(item, float) and not math.isfinite(item) for item in values):
            raise ValueError("evidence values must contain only finite numbers")
        return value


class Evidence(BaseModel):
    """A timestamped evidence item associated with one command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID = Field(default_factory=uuid4)
    command_id: UUID
    kind: EvidenceKind
    source: str = Field(min_length=1)
    facts: tuple[EvidenceFact, ...] = ()
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(timezone.utc)
