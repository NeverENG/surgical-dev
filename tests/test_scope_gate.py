"""Exercise the scope audit against real Git worktrees, not source text."""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scope_gate.py"


class ScopeAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "src").mkdir()
        (self.repo / "src/app.py").write_text("original\n")
        (self.repo / "other.py").write_text("keep\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.state = self.start()

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def gate(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo,
                              text=True, capture_output=True)

    def start(self, *extras):
        result = self.gate("start", "--repo", str(self.repo), "--scope", "src/", *extras)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = re.search(r"状态目录: (.+)", result.stdout).group(1)
        self.addCleanup(lambda: shutil.rmtree(state))
        return state

    def check(self, *args, state=None):
        return self.gate("check", "--state", state or self.state, *args)

    def test_in_scope_change_passes_without_second_signature(self):
        (self.repo / "src/app.py").write_text("changed\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("+changed", result.stdout)
        self.assertIn("src/app.py", result.stdout)

    def test_outside_scope_fails_until_explained(self):
        (self.repo / "other.py").write_text("needed\n")
        self.assertEqual(self.check().returncode, 2)
        result = self.check("--explain", "other.py=本次功能必须调用现有适配层")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("本次功能必须调用现有适配层", result.stdout)

    def test_preexisting_dirty_file_is_preserved_not_misattributed(self):
        (self.repo / "other.py").write_text("preexisting\n")
        state = self.start()
        (self.repo / "src/app.py").write_text("new\n")
        result = self.check(state=state)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("other.py", result.stdout)
        (self.repo / "other.py").write_text("changed again\n")
        self.assertEqual(self.check(state=state).returncode, 2)

    def test_new_file_in_scope_passes_and_outside_fails(self):
        (self.repo / "src/new.py").write_text("new\n")
        self.assertEqual(self.check().returncode, 0)
        (self.repo / "outside.py").write_text("new\n")
        self.assertEqual(self.check().returncode, 2)

    def test_staged_only_change_is_detected_and_reviewable(self):
        (self.repo / "src/app.py").write_text("staged\n")
        self.git("add", "src/app.py")
        (self.repo / "src/app.py").write_text("original\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("+staged", result.stdout)
        self.assertIn("暂存区", result.stdout)

    def test_outside_staged_only_change_fails(self):
        (self.repo / "other.py").write_text("staged\n")
        self.git("add", "other.py")
        (self.repo / "other.py").write_text("keep\n")
        self.assertEqual(self.check().returncode, 2)

    def test_scope_explanation_is_remembered_for_later_checks(self):
        (self.repo / "other.py").write_text("needed\n")
        first = self.check("--explain", "other.py=本次功能新增的必要调用方接口")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.check().returncode, 0)

    def test_new_commit_invalidates_baseline(self):
        self.git("commit", "--allow-empty", "-qm", "later")
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("HEAD", result.stderr)

    def test_preexisting_in_scope_edit_is_not_hidden_in_review(self):
        (self.repo / "src/app.py").write_text("user edit\n")
        state = self.start()
        (self.repo / "src/app.py").write_text("user edit\nnew behavior\n")
        result = self.check(state=state)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("+new behavior", result.stdout)
        self.assertNotIn("-original", result.stdout)

    def test_binary_requires_independent_review(self):
        (self.repo / "src/app.py").write_bytes(b"\x00changed")
        self.assertEqual(self.check().returncode, 3)
        self.assertEqual(self.check("--binary-reviewed").returncode, 0)

    def test_explicit_ignored_file_is_monitored(self):
        (self.repo / ".gitignore").write_text("src/secret.cfg\n")
        (self.repo / "src/secret.cfg").write_text("old\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore config")
        state = self.start("--include", "src/secret.cfg")
        (self.repo / "src/secret.cfg").write_text("new\n")
        result = self.check(state=state)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("src/secret.cfg", result.stdout)

    def test_root_wide_scope_is_rejected(self):
        self.assertEqual(self.gate("start", "--repo", str(self.repo),
                                   "--scope", ".").returncode, 2)


if __name__ == "__main__":
    unittest.main()
