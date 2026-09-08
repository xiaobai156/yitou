from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import msvcrt

_ARTIFACT_WRITE_LOCK = threading.Lock()
_ARTIFACT_LOCK_PATH = Path(".tmp") / "artifact-write.lock"


class ArtifactTransactionRollbackError(RuntimeError):
    """A commit failed and one or more original artifacts could not be restored."""


class ArtifactCleanupWarning(RuntimeError):
    """All artifacts were committed, but temporary backup cleanup failed."""


def commit_artifacts_transaction(artifacts: dict[Path, bytes | None], *, expected: dict[Path, bytes | None] | None = None) -> None:
    """Replace all formal files as one recoverable transaction; None deletes a stale file."""
    with _artifact_write_lock():
        if expected is not None:
            for path, original in expected.items():
                current = path.read_bytes() if path.exists() else None
                if current != original:
                    raise RuntimeError(f"正式文件在重抓期间发生变化，已停止写入：{path}")
        _commit_artifacts_transaction(artifacts)


def _commit_artifacts_transaction(artifacts: dict[Path, bytes | None]) -> None:
    temporary: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    rollback_errors: list[str] = []
    cleanup_errors: list[str] = []
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
                    try:
                        backup.unlink()
                    except BaseException as exc:
                        cleanup_errors.append(f"{backup}清理失败：{exc}")
        if cleanup_errors and not rollback_errors:
            raise ArtifactCleanupWarning("提交成功但备份清理失败：" + "；".join(cleanup_errors))


@contextmanager
def _artifact_write_lock(timeout: float = 30.0):
    """Serialize formal writes across threads and Windows processes."""
    with _ARTIFACT_WRITE_LOCK:
        _ARTIFACT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _ARTIFACT_LOCK_PATH.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("正式文件写入锁等待超时")
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


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
