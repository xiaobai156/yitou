from __future__ import annotations

import os
import time
from pathlib import Path


class ArtifactTransactionRollbackError(RuntimeError):
    """A commit failed and one or more original artifacts could not be restored."""


def commit_artifacts_transaction(artifacts: dict[Path, bytes | None]) -> None:
    """Replace all formal files as one recoverable transaction; None deletes a stale file."""
    temporary: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    rollback_errors: list[str] = []
    try:
        for path, data in artifacts.items():
            if data is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary[path] = temp
        for path in artifacts:
            if path.exists():
                backup = path.with_name(f".{path.name}.{time.time_ns()}.bak")
                path.replace(backup)
                backups[path] = backup
        for path, temp in temporary.items():
            temp.replace(path)
            committed.append(path)
    except BaseException as commit_error:
        rollback_errors = _rollback_artifacts(committed, backups)
        if rollback_errors:
            details = "；".join(rollback_errors)
            raise ArtifactTransactionRollbackError(f"事务回滚失败，已保留可恢复备份：{details}") from commit_error
        raise
    finally:
        for temp in temporary.values():
            if temp.exists():
                temp.unlink()
        if not rollback_errors:
            for backup in backups.values():
                if backup.exists():
                    backup.unlink()


def _rollback_artifacts(committed: list[Path], backups: dict[Path, Path]) -> list[str]:
    errors: list[str] = []
    for path, backup in backups.items():
        if not backup.exists():
            if path.exists():
                errors.append(f"{path}原文件备份已缺失，无法恢复")
            continue
        try:
            backup.replace(path)
        except BaseException as exc:
            errors.append(f"{path}恢复失败：{exc}")
    for path in committed:
        if path in backups or not path.exists():
            continue
        try:
            path.unlink()
        except BaseException as exc:
            errors.append(f"{path}删除新文件失败：{exc}")
    return errors
