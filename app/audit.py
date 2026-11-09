import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def record(
        self,
        *,
        run_id: str,
        code: str,
        policy_hash: str,
        status: str,
        duration_ms: int,
        exit_code: int | None = None,
        violations: list[str] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "code_sha256": sha256_text(code),
            "code_chars": len(code),
            "policy_sha256": policy_hash,
            "status": status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "violations": violations or [],
        }
        line = json.dumps(entry, sort_keys=True)
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return entry

    def find(self, run_id: str) -> dict[str, Any] | None:
        if not RUN_ID_PATTERN.match(run_id) or not self._path.exists():
            return None
        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            entry = json.loads(line)
            if entry["run_id"] == run_id:
                return entry
        return None
