"""Minimal stage 2A tests for the append-only JSONL audit ledger."""

from __future__ import annotations

from datetime import datetime

import pytest

from runtime_core.audit.ledger import AuditLedger
from runtime_core.schemas.audit import AuditRecordType


def test_append_preserves_existing_records_and_one_record_per_line(tmp_path) -> None:
    path = tmp_path / "nested" / "runtime.jsonl"
    ledger = AuditLedger(path)

    first = ledger.append(
        record_type=AuditRecordType.ORGANIZATION_TRANSITION,
        actor="operator",
        world_version=3,
        org_version=2,
        payload={"from_mode": "NORMAL", "to_mode": "WATCH"},
    )
    second = ledger.append(
        record_type=AuditRecordType.ORGANIZATION_TRANSITION,
        actor="weather_monitor",
        world_version=3,
        org_version=3,
        payload={"from_mode": "WATCH", "to_mode": "EMERGENCY"},
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8").count("\n") == 2
    assert ledger.read_all() == (first, second)
    assert ledger.verify_record(first)
    assert ledger.verify_record(second)


def test_naive_audit_timestamp_is_rejected(tmp_path) -> None:
    ledger = AuditLedger(tmp_path / "runtime.jsonl")

    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.append(
            record_type=AuditRecordType.ORGANIZATION_TRANSITION,
            actor="operator",
            world_version=0,
            org_version=1,
            payload={"from_mode": "NORMAL", "to_mode": "WATCH"},
            timestamp=datetime(2026, 7, 20, 8, 0),
        )

