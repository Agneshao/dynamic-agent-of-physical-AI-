"""Durable single-host JSONL transport for the Isaac bridge."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Optional

import fcntl
from pydantic import ValidationError

from runtime_core.schemas.isaac import (
    IsaacBridgeState,
    IsaacCommandRequest,
    IsaacCommandResult,
)


class IsaacFileProtocolError(RuntimeError):
    """Raised when a bridge file violates the shared protocol."""


@dataclass(frozen=True)
class IsaacBridgePaths:
    root: Path
    requests: Path
    results: Path
    state: Path

    @classmethod
    def from_directory(cls, directory: Path | str) -> "IsaacBridgePaths":
        root = Path(directory).expanduser().resolve()
        return cls(
            root=root,
            requests=root / "commands.jsonl",
            results=root / "results.jsonl",
            state=root / "state.json",
        )


class IsaacFileProtocol:
    """One Runtime-side writer and result/state reader."""

    def __init__(
        self,
        directory: Path | str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = IsaacBridgePaths.from_directory(directory)
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._monotonic = monotonic
        self._sleeper = sleeper

    def append_request(self, request: IsaacCommandRequest) -> None:
        self._append_model(self.paths.requests, request.model_dump(mode="json"))

    def append_result(self, result: IsaacCommandResult) -> None:
        """Test/diagnostic helper matching the Isaac-side result writer."""
        self._append_model(self.paths.results, result.model_dump(mode="json"))

    def list_requests(self) -> tuple[IsaacCommandRequest, ...]:
        return self._read_jsonl(self.paths.requests, IsaacCommandRequest)

    def list_results(self) -> tuple[IsaacCommandResult, ...]:
        return self._read_jsonl(self.paths.results, IsaacCommandResult)

    def latest_result(self, action_id: object) -> Optional[IsaacCommandResult]:
        matching = (
            item for item in self.list_results() if str(item.action_id) == str(action_id)
        )
        return next(reversed(tuple(matching)), None)

    def latest_terminal_result(
        self, action_id: object
    ) -> Optional[IsaacCommandResult]:
        matching = tuple(
            item
            for item in self.list_results()
            if str(item.action_id) == str(action_id) and item.status.terminal
        )
        return matching[-1] if matching else None

    def wait_for_terminal_result(
        self,
        action_id: object,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> Optional[IsaacCommandResult]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        deadline = self._monotonic() + timeout_seconds
        while True:
            result = self.latest_terminal_result(action_id)
            if result is not None:
                return result
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return None
            self._sleeper(min(poll_interval_seconds, remaining))

    def read_state(self) -> Optional[IsaacBridgeState]:
        with self._lock:
            try:
                raw = self.paths.state.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
        try:
            return IsaacBridgeState.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise IsaacFileProtocolError("state.json failed validation") from exc

    def write_state(self, state: IsaacBridgeState) -> None:
        """Test/diagnostic helper matching Isaac's atomic state writer."""
        body = state.model_dump_json()
        temporary = self.paths.root / f".{self.paths.state.name}.{os.getpid()}.tmp"
        with self._lock:
            temporary.write_text(body, encoding="utf-8")
            os.replace(temporary, self.paths.state)

    def _append_model(self, path: Path, payload: dict[str, object]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock, path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_jsonl(self, path: Path, model_type: type) -> tuple:
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return ()
        lines = raw.splitlines()
        if raw and not raw.endswith("\n"):
            lines = lines[:-1]
        items = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                items.append(model_type.model_validate_json(line))
            except (ValidationError, ValueError) as exc:
                raise IsaacFileProtocolError(
                    f"{path.name}:{line_number} failed validation"
                ) from exc
        return tuple(items)
