"""Thread-safe append-only JSONL audit ledger."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from runtime_core.schemas.audit import AuditRecord, AuditRecordType


class AuditLedgerError(RuntimeError):
    """Base error raised by the local audit ledger."""


class AuditIntegrityError(AuditLedgerError):
    """Raised when a JSONL record cannot be parsed or its checksum is invalid."""


class AuditLedger:
    """Append and verify audit records in a local JSONL file.

    The ledger provides a single-process consistency boundary guarded by an
    RLock. It is not a distributed transaction log or a cryptographic signing
    system.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    @property
    def path(self) -> Path:
        """Return the configured ledger path."""
        return self._path

    def append(
        self,
        *,
        record_type: AuditRecordType,
        actor: str,
        world_version: int,
        org_version: int,
        payload: dict[str, JsonValue],
        timestamp: Optional[datetime] = None,
    ) -> AuditRecord:
        """Validate, checksum, and append exactly one JSON record line."""
        record_time = timestamp or datetime.now(timezone.utc)
        base_data = {
            "record_id": uuid4(),
            "record_type": record_type,
            "timestamp": record_time,
            "actor": actor,
            "world_version": world_version,
            "org_version": org_version,
            "payload": payload,
        }
        checksum = self._checksum_for_data(base_data)
        record = AuditRecord.model_validate({**base_data, "checksum": checksum})
        serialized = record.model_dump_json()

        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(serialized)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise AuditLedgerError(f"failed to append audit record: {exc}") from exc
        return record

    def read_all(self, *, verify: bool = True) -> tuple[AuditRecord, ...]:
        """Read all records and optionally verify every checksum."""
        records: list[AuditRecord] = []
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise AuditLedgerError(f"failed to read audit ledger: {exc}") from exc

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = AuditRecord.model_validate_json(line)
            except ValidationError as exc:
                raise AuditIntegrityError(
                    f"invalid audit record at line {line_number}"
                ) from exc
            if verify and not self.verify_record(record):
                raise AuditIntegrityError(
                    f"checksum mismatch at line {line_number}"
                )
            records.append(record)
        return tuple(records)

    def verify_record(self, record: AuditRecord) -> bool:
        """Return whether one record's checksum matches its content."""
        data = record.model_dump(mode="python", exclude={"checksum"})
        return self._checksum_for_data(data) == record.checksum

    @staticmethod
    def _checksum_for_data(data: dict[str, object]) -> str:
        canonical = json.dumps(
            AuditLedger._json_compatible(data),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _json_compatible(value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("audit timestamps must be timezone-aware")
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if hasattr(value, "value"):
            return getattr(value, "value")
        if isinstance(value, dict):
            return {
                str(key): AuditLedger._json_compatible(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [AuditLedger._json_compatible(item) for item in value]
        return str(value) if isinstance(value, UUID) else value
