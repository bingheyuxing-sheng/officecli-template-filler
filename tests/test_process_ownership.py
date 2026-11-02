# -*- coding: utf-8 -*-
"""
v3.5 M7 — Process ownership tests.

Cleanup may only terminate a process this task can prove it owns: `(pid, image,
creation time)` recorded when the process was started. Anything unprovable is reported
in `unreleased_pids` instead of being killed on a guess.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import process_guard
from engine.process_guard import EditorSdkSession, process_identity, task_cleanup_log_path


class TestProcessOwnershipSuite(unittest.TestCase):
    def test_v35_process_identity_includes_creation_time(self) -> None:
        """Identity is `(pid, image, creation time)` on every platform, Windows included."""
        identity = process_identity(os.getpid())
        self.assertEqual(identity["pid"], os.getpid())
        self.assertTrue(identity["image"])
        self.assertIsInstance(identity["start_ticks"], int)

    def test_v35_cleanup_only_terminates_spawned_pids(self) -> None:
        """A recorded spawned PID is terminated; other new processes are left alone."""
        terminated = []
        live = iter([[101], [101, 202, 303]])

        def fake_terminate(pid, expected_name=None, popen=None, expected_ticks=None):
            terminated.append((pid, expected_ticks))
            return True

        with mock.patch.object(process_guard, "list_process_pids", side_effect=lambda name: next(live)), \
             mock.patch.object(process_guard, "process_start_ticks", side_effect=lambda pid: 1000 + pid), \
             mock.patch.object(process_guard.TaskResourceGuard, "_terminate_single_pid", side_effect=fake_terminate), \
             mock.patch.object(process_guard.TaskResourceGuard, "_is_pid_running", return_value=False):
            session = EditorSdkSession(image_name="editor_sdk.exe", task_id="task-a")
            session.record_baseline()
            session.note_spawned([202])
            result = session.stop_new_instances(verify_timeout_ms=0)

        self.assertEqual([pid for pid, _ticks in terminated], [202])
        self.assertEqual(terminated[0][1], 1202)
        self.assertEqual(result["ownership_source"], "spawned_pids")
        self.assertEqual(result["spawned_during_task"], [202])
        self.assertEqual(result["task_id"], "task-a")
        self.assertTrue(result["verified"])

    def test_v35_unreleased_pids_reported(self) -> None:
        """Without a verifiable creation time the process is reported, never terminated."""
        calls = []
        live = iter([[404], [404, 505]])

        with mock.patch.object(process_guard, "list_process_pids", side_effect=lambda name: next(live)), \
             mock.patch.object(process_guard, "process_start_ticks", return_value=None), \
             mock.patch.object(
                 process_guard.TaskResourceGuard,
                 "_terminate_single_pid",
                 side_effect=lambda *args, **kwargs: calls.append(args) or True,
             ), \
             mock.patch.object(process_guard.TaskResourceGuard, "_is_pid_running", return_value=False):
            session = EditorSdkSession(image_name="editor_sdk.exe", task_id="task-b")
            session.record_baseline()
            result = session.stop_new_instances(verify_timeout_ms=0)

        self.assertEqual(calls, [])
        self.assertEqual(result["unreleased_pids"], [505])
        self.assertFalse(result["verified"])
        self.assertEqual(result["ownership_source"], "baseline_diff")

    def test_v35_cleanup_log_is_per_task(self) -> None:
        """Concurrent tasks must not overwrite each other's cleanup evidence."""
        task_id = "task-42/weird"
        path = task_cleanup_log_path(task_id)
        self.assertIn("task-42_weird", os.path.basename(path))
        try:
            process_guard._write_auto_cleanup_log({"verified": True}, task_id=task_id)
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(process_guard.AUTO_CLEANUP_LOG))
        finally:
            if os.path.isfile(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
