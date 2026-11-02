"""
Task-Scoped Process & Resource Ownership Manager (v3.0 — Fixes P0-4).

Replaces global `taskkill /F /IM editor_sdk.exe /IM officecli.exe` with strict
task-scoped PID ownership tracking and explicit resource closing (file handles,
ZipFile, openpyxl Workbooks, COM document objects).
"""
from __future__ import annotations

import atexit
import gc
import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Placeholder names that carry no image identity, so the live-name equality check is skipped.
_NAME_CHECK_EXEMPT = {"subproc", "explicit_pid"}


@dataclass
class OwnedProcess:
    pid: int
    name: str
    cmd: List[str] = field(default_factory=list)
    popen: Any = None


class TaskResourceGuard:
    """
    Context-managed resource & process owner for a single Office document task.
    Guarantees that ONLY subprocesses spawned by this task (`owned_processes`)
    and resources registered to this task are closed on exit—never killing
    concurrent tasks' `officecli.exe` or `editor_sdk.exe` instances.
    """

    def __init__(self, task_id: Optional[str] = None):
        self.task_id: str = task_id or f"job_{uuid.uuid4().hex[:8]}"
        self.owned_processes: List[OwnedProcess] = []
        self._open_resources: List[Any] = []
        self._com_documents: List[Any] = []

    def __enter__(self) -> "TaskResourceGuard":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release_all()

    def register_resource(self, obj: Any) -> Any:
        """Register a Python file handle, ZipFile, or openpyxl Workbook for explicit close()."""
        if obj is not None and obj not in self._open_resources:
            self._open_resources.append(obj)
        return obj

    def register_com_document(self, com_doc: Any) -> Any:
        """Register a win32com Word/Excel Document/Workbook object for explicit Close(SaveChanges=False)."""
        if com_doc is not None and com_doc not in self._com_documents:
            self._com_documents.append(com_doc)
        return com_doc

    def register_pid(
        self,
        pid: int,
        name: str = "subproc",
        cmd: Optional[List[str]] = None,
        popen: Any = None,
    ) -> OwnedProcess:
        """
        Record a child process PID owned by this task.

        When the live `subprocess.Popen` handle is supplied, release uses `poll()` to prove the
        process is still alive, which avoids terminating an unrelated process that reused the PID.
        """
        entry = OwnedProcess(pid=int(pid), name=name, cmd=list(cmd or []), popen=popen)
        self.owned_processes.append(entry)
        return entry

    def run_owned_command(
        self,
        cmd: List[str],
        timeout: int = 60,
        cwd: Optional[str] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Spawn a subprocess (`officecli`, `soffice`, etc.), track its exact PID in
        `owned_processes`, wait for completion, and terminate ONLY that PID if it hangs.
        """
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        proc_name = os.path.basename(cmd[0]) if cmd else "subproc"
        owned = self.register_pid(proc.pid, name=proc_name, cmd=cmd, popen=proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._terminate_single_pid(owned.pid, expected_name=owned.name, popen=proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            if check:
                raise
        finally:
            if owned in self.owned_processes and proc.poll() is not None:
                self.owned_processes.remove(owned)

        result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
        return result

    @staticmethod
    def _query_windows_process_name(pid: int) -> Optional[str]:
        """
        Return the image name for `pid` on Windows, or `None` when the PID is not running.

        Uses CSV output and parses the exact PID column instead of substring matching, so a PID
        that merely appears inside a memory-size column can never be treated as alive.
        """
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return None
        out = (res.stdout or "").strip()
        if not out or out.upper().startswith("INFO:"):
            return None
        for line in out.splitlines():
            cols = [c.strip().strip('"') for c in line.split('","')]
            if len(cols) < 2:
                continue
            cols[0] = cols[0].lstrip('"')
            cols[-1] = cols[-1].rstrip('"')
            name, pid_col = cols[0], cols[1]
            if pid_col == str(pid):
                return name
        return None

    @staticmethod
    def _is_pid_running(pid: int, expected_name: Optional[str] = None) -> bool:
        """
        Check whether `pid` is still alive.

        When `expected_name` is given, the live image name must match it, which prevents acting on
        an unrelated process that has reused a previously owned PID. This check runs on every
        platform: Linux reads `/proc/<pid>/comm` instead of trusting a `pgrep -f` command-line match.
        """
        if pid <= 0:
            return False
        if os.name == "nt":
            live_name = TaskResourceGuard._query_windows_process_name(pid)
            if live_name is None:
                return False
            if expected_name and expected_name not in _NAME_CHECK_EXEMPT:
                live_base = os.path.basename(live_name).lower()
                expected_base = os.path.basename(expected_name).lower()
                if not expected_base.endswith(".exe"):
                    expected_base += ".exe"
                if live_base != expected_base:
                    return False
            return True
        live_name = process_image_name(pid)
        if live_name is None:
            return False
        if expected_name and expected_name not in _NAME_CHECK_EXEMPT:
            expected_base = os.path.basename(expected_name).lower()
            if expected_base.endswith(".exe"):
                expected_base = expected_base[: -len(".exe")]
            live_base = os.path.basename(live_name).lower()
            if live_base.endswith(".exe"):
                live_base = live_base[: -len(".exe")]
            if live_base != expected_base:
                return False
        return True

    @classmethod
    def _terminate_single_pid(
        cls,
        pid: int,
        expected_name: Optional[str] = None,
        popen: Any = None,
        expected_ticks: Optional[int] = None,
    ) -> bool:
        """
        Terminate ONLY the specified PID, never `/IM` by process name.

        Guards against PID reuse:
        - A live `Popen` handle is preferred: `poll()` decides liveness and the handle is used
          to terminate, so a recycled PID is never touched.
        - Otherwise the live image name AND creation time must match the recorded identity.
        """
        if popen is not None:
            if popen.poll() is not None:
                return False
            try:
                popen.terminate()
                return True
            except Exception:
                return False
        if expected_ticks is not None:
            live_ticks = process_start_ticks(pid)
            if live_ticks is None or live_ticks != expected_ticks:
                return False
        if not cls._is_pid_running(pid, expected_name=expected_name):
            return False
        if os.name == "nt":
            # No `/T`: children are only terminated when their own identity is proven.
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return True
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False

    def snapshot_ownership(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owned_processes": [
                {"pid": p.pid, "name": p.name, "cmd": p.cmd}
                for p in self.owned_processes
            ],
            "registered_resources_count": len(self._open_resources),
            "registered_com_count": len(self._com_documents),
        }

    def release_all(self) -> Dict[str, Any]:
        """
        Explicitly close all registered COM objects, Workbooks, ZipFiles, file handles,
        and terminate ONLY PIDs in `self.owned_processes`, then run `gc.collect()`.
        """
        closed_resources = 0
        closed_com = 0
        terminated_pids: List[int] = []

        # 1. Close COM document objects first
        for com_doc in reversed(self._com_documents):
            try:
                if hasattr(com_doc, "Close"):
                    com_doc.Close(False)
                    closed_com += 1
            except Exception:
                pass
        self._com_documents.clear()

        # 2. Close Python file handles, ZipFile, openpyxl Workbook objects
        for res in reversed(self._open_resources):
            try:
                if hasattr(res, "close") and callable(res.close):
                    res.close()
                    closed_resources += 1
            except Exception:
                pass
        self._open_resources.clear()

        # 3. Terminate ONLY task-owned PIDs (never global /IM; never a reused PID)
        for owned in list(self.owned_processes):
            if self._terminate_single_pid(owned.pid, expected_name=owned.name, popen=owned.popen):
                terminated_pids.append(owned.pid)
        self.owned_processes.clear()

        gc.collect()
        return {
            "task_id": self.task_id,
            "closed_resources": closed_resources,
            "closed_com_documents": closed_com,
            "terminated_pids": terminated_pids,
        }


def release_office_file_locks(
    guard: Optional[TaskResourceGuard] = None,
    owned_pids: Optional[List[int]] = None,
    open_resources: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Safe v3.0 replacement for `release_office_file_locks()`.
    NEVER executes global `taskkill /IM`. Only closes resources and PIDs explicitly
    owned by the current task (`guard`, `owned_pids`, `open_resources`).
    """
    active_guard = guard or TaskResourceGuard()
    for res in (open_resources or []):
        active_guard.register_resource(res)
    for pid in (owned_pids or []):
        active_guard.register_pid(int(pid), name="explicit_pid")
    return active_guard.release_all()


EDITOR_SDK_IMAGE = "editor_sdk.exe"


def process_image_name(pid: int) -> Optional[str]:
    """
    Exact image name for `pid` on any platform.

    Linux reads `/proc/<pid>/comm` rather than `pgrep -f`, which would match a substring of
    any process's command line and could terminate an unrelated process.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        return TaskResourceGuard._query_windows_process_name(pid)
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def process_start_ticks(pid: int) -> Optional[int]:
    """
    Kernel start time of `pid`, or None when it cannot be read.

    Paired with the PID, this rejects PID reuse: a recycled PID has a different start time,
    so a stale record can never justify terminating the new owner of that number. Windows
    uses `GetProcessTimes` through ctypes; Linux reads `/proc/<pid>/stat`.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_start_ticks(pid)
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as handle:
            fields = handle.read().split()
        return int(fields[21])
    except (OSError, IndexError, ValueError):
        return None


def _windows_process_start_ticks(pid: int) -> Optional[int]:
    """Creation time of a Windows process (100 ns units since 1601), or None."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            )
            if not ok:
                return None
            return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def process_identity(pid: int) -> Dict[str, Any]:
    """`(pid, image, creation time)` — the tuple a task must prove before terminating."""
    return {
        "pid": pid,
        "image": process_image_name(pid),
        "start_ticks": process_start_ticks(pid),
    }


def list_process_pids(image_name: str) -> List[int]:
    """
    Return live PIDs for `image_name` without any name-substring matching.

    Used by `EditorSdkSession` so a document task can prove which SDK instances it
    started and which ones predate it.
    """
    if os.name != "nt":
        try:
            res = subprocess.run(
                ["pgrep", "-x", os.path.basename(image_name).replace(".exe", "")],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
        except OSError:
            return []
        return [int(line) for line in (res.stdout or "").split() if line.isdigit()]

    try:
        res = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []

    pids: List[int] = []
    expected = image_name.lower()
    for line in (res.stdout or "").splitlines():
        cols = [c.strip().strip('"') for c in line.split('","')]
        if len(cols) < 2:
            continue
        name = cols[0].lstrip('"').lower()
        if name != expected:
            continue
        try:
            pids.append(int(cols[1]))
        except ValueError:
            continue
    return pids


class EditorSdkSession:
    """
    Snapshot `editor_sdk.exe` before a document task and terminate only the instances that
    appeared afterwards.

    This is the safe answer to "the SDK keeps the DOCX locked after the agent finished":
    a pre-existing SDK that the user opened keeps running, while every SDK spawned during
    this task is stopped and verified gone.
    """

    def __init__(
        self,
        image_name: str = EDITOR_SDK_IMAGE,
        baseline_pids: Optional[List[int]] = None,
        task_id: Optional[str] = None,
    ):
        self.image_name = image_name
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.baseline_pids: List[int] = list(baseline_pids or [])
        self.baseline_identities: List[Tuple[int, Optional[int]]] = [
            (pid, process_start_ticks(pid)) for pid in self.baseline_pids
        ]
        self._recorded = baseline_pids is not None
        # PIDs this task is actually known to have started. When set, cleanup is
        # proof-based instead of "whatever appeared after the snapshot".
        self.spawned_pids: List[int] = []

    def note_spawned(self, pids: List[int]) -> List[int]:
        """Record PIDs this task started, so cleanup can prove ownership."""
        for pid in pids:
            try:
                value = int(pid)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in self.spawned_pids:
                self.spawned_pids.append(value)
        return self.spawned_pids

    def record_baseline(self) -> List[int]:
        self.baseline_identities = [
            (pid, process_start_ticks(pid)) for pid in list_process_pids(self.image_name)
        ]
        self.baseline_pids = [pid for pid, _ticks in self.baseline_identities]
        self._recorded = True
        return self.baseline_pids

    def _live_identities(self) -> List[Tuple[int, Optional[int]]]:
        return [(pid, process_start_ticks(pid)) for pid in list_process_pids(self.image_name)]

    def stop_new_instances(self, verify_timeout_ms: int = 1000) -> Dict[str, Any]:
        """
        Terminate SDK instances this task can prove it owns, then verify they are gone.

        Ownership is `(pid, creation time)` from `spawned_pids` when available; otherwise the
        baseline difference is used and reported as such. A candidate whose creation time
        cannot be read is reported in `unreleased_pids` instead of being killed on a guess.
        """
        if not self._recorded:
            raise RuntimeError("call record_baseline() before stop_new_instances()")

        baseline_set = set(self.baseline_identities)
        detected = [item for item in self._live_identities() if item not in baseline_set]
        if self.spawned_pids:
            owned = {int(pid) for pid in self.spawned_pids}
            candidates = [item for item in detected if item[0] in owned]
            ownership_source = "spawned_pids"
        else:
            candidates = detected
            ownership_source = "baseline_diff"

        unproven = [pid for pid, ticks in candidates if ticks is None]
        actionable = [(pid, ticks) for pid, ticks in candidates if ticks is not None]
        terminated: List[int] = []
        skipped_identity: List[int] = []

        for pid, ticks in actionable:
            live_ticks = process_start_ticks(pid)
            if live_ticks != ticks:
                # PID was reused between snapshot and termination; not the process we targeted.
                skipped_identity.append(pid)
                continue
            if TaskResourceGuard._terminate_single_pid(
                pid, expected_name=self.image_name, expected_ticks=ticks
            ):
                terminated.append(pid)

        remaining: List[int] = []
        waited = 0
        while waited < verify_timeout_ms:
            remaining = [
                pid for pid, _ticks in actionable
                if TaskResourceGuard._is_pid_running(pid, expected_name=self.image_name)
            ]
            if not remaining:
                break
            time.sleep(0.1)
            waited += 100

        return {
            "task_id": self.task_id,
            "baseline_pids": self.baseline_pids,
            "spawned_during_task": [pid for pid, _ticks in candidates],
            "ownership_source": ownership_source,
            "terminated_pids": terminated,
            "skipped_identity_mismatch": skipped_identity,
            "unreleased_pids": unproven,
            "still_running": remaining,
            "verified": not remaining and not unproven,
        }


AUTO_CLEANUP_LOG = os.path.join(tempfile.gettempdir(), "officecli_editor_sdk_cleanup.json")

_auto_cleanup_session: Optional[EditorSdkSession] = None


def task_cleanup_log_path(task_id: str) -> str:
    """Per-task cleanup log, so concurrent tasks never overwrite each other's evidence."""
    safe = "".join(
        character if (character.isalnum() or character in "._-") else "_"
        for character in str(task_id or "task")
    )
    return os.path.join(tempfile.gettempdir(), f"officecli_editor_sdk_cleanup_{safe}.json")


def _write_auto_cleanup_log(payload: Dict[str, Any], task_id: Optional[str] = None) -> None:
    targets = [AUTO_CLEANUP_LOG]
    if task_id:
        targets.append(task_cleanup_log_path(task_id))
    for target in targets:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass


def _run_auto_cleanup() -> None:
    """atexit hook: stop SDK instances that appeared while this CLI process ran."""
    if _auto_cleanup_session is None:
        return
    try:
        result = _auto_cleanup_session.stop_new_instances()
        result["timestamp"] = int(time.time())
        result["source_process"] = os.getpid()
        result["task_id"] = _auto_cleanup_session.task_id
        _write_auto_cleanup_log(result, task_id=_auto_cleanup_session.task_id)
    except Exception as exc:  # cleanup must never turn a successful task into a crash
        _write_auto_cleanup_log({
            "verified": False,
            "error": f"{type(exc).__name__}: {exc}",
            "source_process": os.getpid(),
            "task_id": _auto_cleanup_session.task_id,
        }, task_id=_auto_cleanup_session.task_id)


def install_auto_cleanup(image_name: str = EDITOR_SDK_IMAGE) -> EditorSdkSession:
    """
    Enable automatic SDK cleanup for the current CLI process.

    Records the baseline immediately and registers an `atexit` hook, so every skill entrypoint
    closes the `editor_sdk.exe` instances it triggered without the agent having to run a
    separate `--start` / `--stop` command. Calling this more than once reuses the first session.

    Set `OFFICECLI_DISABLE_AUTO_CLEANUP=1` to opt out (used when hosting the engine inside a
    longer-lived process that must not terminate SDKs on its own exit).
    """
    global _auto_cleanup_session
    if _auto_cleanup_session is not None:
        return _auto_cleanup_session
    if os.environ.get("OFFICECLI_DISABLE_AUTO_CLEANUP") == "1":
        # No baseline is recorded and no hook is registered, so nothing can be terminated.
        _auto_cleanup_session = EditorSdkSession(image_name=image_name)
        return _auto_cleanup_session

    session = EditorSdkSession(image_name=image_name)
    session.record_baseline()
    _auto_cleanup_session = session
    atexit.register(_run_auto_cleanup)
    return session


def read_auto_cleanup_log() -> Dict[str, Any]:
    """Return the last automatic cleanup result written by `install_auto_cleanup()`."""
    try:
        with open(AUTO_CLEANUP_LOG, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}
