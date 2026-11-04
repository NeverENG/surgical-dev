"""Behavioral checks for the post-change scope gate."""

import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scope_gate.py"


class ScopeGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("first\n")
        (self.repo / "other.py").write_text("keep\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "initial")
        result = self.gate("start", "--repo", str(self.repo), "--allow", "app.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.state = re.search(r"状态目录: (.+)", result.stdout).group(1)
        self.addCleanup(lambda: shutil.rmtree(self.state))

    def run_git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def gate(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo,
                              text=True, capture_output=True)

    def check(self, *args):
        return self.gate("check", "--state", self.state, *args)

    def test_attestation_uses_exact_current_diff(self):
        (self.repo / "app.py").write_text("first\nneeded\n")
        review = self.check()
        self.assertEqual(review.returncode, 3)
        self.assertIn("+needed", review.stdout)
        digest = re.search(r"本次指纹: ([a-f0-9]+)", review.stdout).group(1)
        self.assertEqual(self.check("--attest", digest).returncode, 0)
        (self.repo / "app.py").write_text("first\nneeded\nunrelated\n")
        self.assertEqual(self.check("--attest", digest).returncode, 3)

    def test_unrelated_change_fails_and_cannot_be_allowlisted_afterwards(self):
        (self.repo / "other.py").write_text("oops\n")
        self.assertEqual(self.check().returncode, 2)
        result = self.gate("extend", "--state", self.state, "--allow", "other.py",
                           "--reason", "necessary for the contract")
        self.assertEqual(result.returncode, 2)

    def test_new_file_must_be_allowlisted_before_editing(self):
        result = self.gate("extend", "--state", self.state, "--allow", "new.py",
                           "--reason", "necessary for the contract")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.repo / "new.py").write_text("new\n")
        self.assertEqual(self.check().returncode, 3)

    def test_staged_only_content_is_visible_for_review(self):
        (self.repo / "app.py").write_text("staged\n")
        self.run_git("add", "app.py")
        (self.repo / "app.py").write_text("first\n")
        review = self.check()
        self.assertEqual(review.returncode, 3)
        self.assertIn("暂存区与工作区内容不同", review.stdout)
        self.assertIn("+staged", review.stdout)

    def test_out_of_scope_index_only_change_is_rejected(self):
        (self.repo / "other.py").write_text("staged\n")
        self.run_git("add", "other.py")
        (self.repo / "other.py").write_text("keep\n")
        self.assertEqual(self.check().returncode, 2)

    def test_explicit_ignored_file_is_monitored(self):
        (self.repo / ".gitignore").write_text("ignored.cfg\n")
        (self.repo / "ignored.cfg").write_text("old\n")
        self.run_git("add", ".gitignore")
        self.run_git("commit", "-qm", "ignore config")
        second = self.gate("start", "--repo", str(self.repo), "--allow", "ignored.cfg")
        self.assertEqual(second.returncode, 0, second.stderr)
        another_state = re.search(r"状态目录: (.+)", second.stdout).group(1)
        self.addCleanup(lambda: shutil.rmtree(another_state))
        (self.repo / "ignored.cfg").write_text("new\n")
        review = self.gate("check", "--state", another_state)
        self.assertEqual(review.returncode, 3)
        self.assertIn("ignored.cfg", review.stdout)
        self.assertIn("+new", review.stdout)

    def test_binary_change_needs_separate_review_flag(self):
        (self.repo / "app.py").write_bytes(b"\x00new bytes")
        review = self.check()
        self.assertEqual(review.returncode, 3)
        digest = re.search(r"本次指纹: ([a-f0-9]+)", review.stdout).group(1)
        self.assertEqual(self.check("--attest", digest).returncode, 3)
        self.assertEqual(self.check("--attest", digest, "--binary-reviewed").returncode, 0)

    def test_preexisting_dirty_file_is_baseline_not_task_change(self):
        (self.repo / "other.py").write_text("preexisting\n")
        second = self.gate("start", "--repo", str(self.repo), "--allow", "app.py")
        self.assertEqual(second.returncode, 0, second.stderr)
        another_state = re.search(r"状态目录: (.+)", second.stdout).group(1)
        self.addCleanup(lambda: shutil.rmtree(another_state))
        (self.repo / "app.py").write_text("changed\n")
        result = self.gate("check", "--state", another_state)
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("other.py", result.stdout)

    def test_out_of_scope_deletion_is_rejected(self):
        (self.repo / "other.py").unlink()
        self.assertEqual(self.check().returncode, 2)


if __name__ == "__main__":
    unittest.main()
