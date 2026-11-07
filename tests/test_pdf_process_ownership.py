# -*- coding: utf-8 -*-
"""PROC-01: PDF converters must run under task-scoped ownership.

``subprocess.run(timeout=...)`` only terminates the direct child.  WPS starts
``wps.exe`` from ``kwpsconvert.exe``, so a timed-out conversion could leave a
helper running.  The PDF backend now runs through ``TaskResourceGuard`` with
``kill_tree=True``; these tests pin the wiring and the actual tree termination.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import engine.pdf_backend as pdf_backend
from engine.process_guard import TaskResourceGuard


class PdfBackendOwnershipWiringTests(unittest.TestCase):
    def test_run_uses_guard_with_tree_termination(self) -> None:
        captured = {}

        class _FakeGuard:
            def __init__(self, task_id=None):
                captured["task_id"] = task_id

            def run_owned_command(self, cmd, **kwargs):
                captured["cmd"] = list(cmd)
                captured.update(kwargs)
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

            def release_all(self):
                captured["released"] = True

        with mock.patch.object(pdf_backend, "TaskResourceGuard", _FakeGuard):
            code, stdout, stderr = pdf_backend._run(["converter", "arg"], 7)

        self.assertEqual((code, stdout, stderr), (0, "ok", ""))
        self.assertEqual(captured["cmd"], ["converter", "arg"])
        self.assertEqual(captured["timeout"], 7)
        self.assertTrue(captured["kill_tree"])
        self.assertTrue(captured["raise_on_timeout"])
        self.assertTrue(captured["released"])


class ProcessTreeTerminationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="proc-tree-")
        self.pid_file = os.path.join(self.tmp.name, "pids.txt")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _spawn_parent_with_child(self) -> list:
        code = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as handle:\n"
            "    handle.write('%d %d' % (os.getpid(), child.pid))\n"
            "time.sleep(60)\n"
        )
        # os is needed inside the child snippet.
        code = "import os\n" + code
        guard = TaskResourceGuard(task_id="proc-tree-test")
        with self.assertRaises(subprocess.TimeoutExpired):
            guard.run_owned_command(
                [sys.executable, "-c", code, self.pid_file],
                timeout=3,
                kill_tree=True,
                raise_on_timeout=True,
            )
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.isfile(self.pid_file):
            time.sleep(0.05)
        self.assertTrue(os.path.isfile(self.pid_file), "helper did not report its PIDs")
        with open(self.pid_file, "r", encoding="utf-8") as handle:
            return [int(part) for part in handle.read().split()]

    def test_timeout_terminates_parent_and_child(self) -> None:
        parent_pid, child_pid = self._spawn_parent_with_child()
        deadline = time.time() + 10
        try:
            while time.time() < deadline:
                if not TaskResourceGuard._is_pid_running(parent_pid) and not TaskResourceGuard._is_pid_running(child_pid):
                    break
                time.sleep(0.1)
            self.assertFalse(TaskResourceGuard._is_pid_running(parent_pid), "parent survived tree kill")
            self.assertFalse(TaskResourceGuard._is_pid_running(child_pid), "child survived tree kill")
        finally:
            for pid in (parent_pid, child_pid):
                if TaskResourceGuard._is_pid_running(pid):
                    TaskResourceGuard._terminate_single_pid(pid)


if __name__ == "__main__":
    unittest.main()
