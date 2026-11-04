#!/usr/bin/env python3
"""Audit changed paths against a planned scope in a Git worktree.

The baseline includes tracked and non-ignored files (plus explicit ignored paths),
as well as the index. Source copies for pre-existing dirty files are kept in the
owner-only temporary state directory so the user's prior edits stay distinguishable.
"""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def repo_root(path):
    return Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel")).strip()).resolve()


def relative(raw, directory=False):
    trimmed = raw.rstrip("/")
    if (not trimmed or trimmed == "." or raw.startswith("/") or "\\" in raw or
            any(ch in raw for ch in "*?[") or
            any(part in ("", ".", "..") for part in trimmed.split("/"))):
        raise ValueError(f"需要明确的仓库相对路径，不接受整个仓库或通配符: {raw!r}")
    return trimmed + ("/" if directory else "")


def byteset(raw):
    return {os.fsdecode(item) for item in raw.split(b"\0") if item}


def tracked_paths(root):
    return byteset(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"))


def fingerprint(path):
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            kind, content = "link", os.fsencode(os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            kind, content = "file", path.read_bytes()
        else:
            raise ValueError(f"不支持的文件类型，请单独核查: {path}")
        return f"{kind}:{stat.S_IMODE(info.st_mode):o}:{hashlib.sha256(content).hexdigest()}"
    except FileNotFoundError:
        return "absent"


def content(path):
    if path.is_symlink():
        return os.fsencode(os.readlink(path))
    return path.read_bytes() if path.is_file() else b""


def scan(root, included):
    return {p: fingerprint(root / p) for p in sorted(tracked_paths(root) | set(included))}


def staged(root):
    entries = git(root, "ls-files", "--stage", "-z").split(b"\0")
    return {os.fsdecode(row.split(b"\t", 1)[1]): row.split(b"\t", 1)[0].decode("ascii")
            for row in entries if row}


def head_of(root):
    try:
        return os.fsdecode(git(root, "rev-parse", "--verify", "HEAD")).strip()
    except subprocess.CalledProcessError:
        return None


def save(state, data):
    draft = state / "manifest.tmp"
    draft.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    draft.replace(state / "manifest.json")


def load(state):
    data = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
    if data.get("version") != 2:
        raise ValueError("旧版闸门状态不兼容，请在修改前重新建立基线")
    return data


def in_scope(path, scopes):
    return any(path.startswith(scope) if scope.endswith("/") else path == scope
               for scope in scopes)


def start(args):
    root = repo_root(args.repo)
    scopes = [relative(s, s.endswith("/") or (root / s).is_dir()) for s in args.scope]
    included = [relative(p) for p in args.include]
    baseline = scan(root, included)
    index = staged(root)
    head = head_of(root)
    dirty = byteset(git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    if head:
        dirty |= byteset(git(root, "diff", "HEAD", "--name-only", "-z"))
        dirty |= byteset(git(root, "diff", "--cached", "HEAD", "--name-only", "-z"))
    else:
        dirty |= set(baseline)
    dirty |= set(included)
    state = Path(tempfile.mkdtemp(prefix="surgical-dev-gate-"))
    (state / "baseline").mkdir()
    snapshots = {}
    for path in sorted(dirty):
        if path not in baseline or baseline[path] == "absent":
            continue
        data = content(root / path)
        if len(data) > 2_000_000:
            continue  # Large pre-existing files require independent review.
        file = hashlib.sha256(os.fsencode(path)).hexdigest()
        (state / "baseline" / file).write_bytes(data)
        snapshots[path] = file
    save(state, {"version": 2, "root": str(root), "head": head,
                 "scope": scopes, "included": included, "baseline": baseline,
                 "index": index, "snapshots": snapshots, "explanations": {}})
    print(f"状态目录: {state}\n方案范围: {', '.join(scopes)}")


def baseline_content(root, state, data, path):
    if path in data["snapshots"]:
        return (state / "baseline" / data["snapshots"][path]).read_bytes(), False
    if data["baseline"].get(path, "absent") == "absent":
        return b"", False
    if data["head"]:
        try:
            return git(root, "show", f"{data['head']}:{path}"), False
        except subprocess.CalledProcessError:
            pass
    return b"", True


def show_diff(before, after, path, label):
    if b"\0" in before + after:
        print(f"  {label}: 二进制内容，需另行核查")
        return True
    try:
        old = before.decode("utf-8").splitlines(keepends=True)
        new = after.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        print(f"  {label}: 非 UTF-8 内容，需另行核查")
        return True
    print("".join(difflib.unified_diff(old, new, fromfile=f"baseline/{path}",
                                       tofile=f"{label}/{path}")), end="\n")
    return False


def check(args):
    state = Path(args.state).resolve()
    data = load(state)
    root = Path(data["root"])
    if repo_root(root) != root or head_of(root) != data["head"]:
        raise ValueError("仓库位置或 HEAD 已变化，不能复用本次基线")
    current = scan(root, data["included"])
    index = staged(root)
    paths = set(data["baseline"]) | set(current) | set(data["index"]) | set(index)
    changed = sorted(p for p in paths if
                     current.get(p, "absent") != data["baseline"].get(p, "absent") or
                     index.get(p) != data["index"].get(p))
    explanations = data["explanations"].copy()
    for entry in args.explain:
        if "=" not in entry:
            raise ValueError("解释格式为 --explain '相对路径=对应需求与必要性'")
        raw, reason = entry.split("=", 1)
        path = relative(raw)
        if path not in changed or in_scope(path, data["scope"]) or not reason.strip():
            raise ValueError(f"只能解释本次实际越界的文件: {path}")
        explanations[path] = reason.strip()
    print("本次变更:", ", ".join(changed) or "无")
    unexplained, nontext = [], False
    for path in changed:
        planned = in_scope(path, data["scope"])
        reason = "方案范围" if planned else explanations.get(path)
        print(f"\n[{ '范围内' if planned else '范围外' }] {path}" +
              (f" | 理由: {reason}" if reason else " | 缺少理由"))
        if not reason:
            unexplained.append(path)
        before, unknown = baseline_content(root, state, data, path)
        if unknown:
            print("  无法还原此文件的基线内容，须单独核查")
            nontext = True
        after = content(root / path)
        if not unknown:
            nontext |= show_diff(before, after, path, "working")
        if index.get(path) != data["index"].get(path):
            staged_bytes = git(root, "show", ":" + path) if path in index else b""
            if staged_bytes != after or before == after:
                print("  暂存区与工作区内容不同:")
                if not unknown:
                    nontext |= show_diff(before, staged_bytes, path, "staged")
    if unexplained:
        print("范围闸门未通过，须撤回或解释:", ", ".join(unexplained), file=sys.stderr)
        return 2
    if nontext and not args.binary_reviewed:
        print("部分差异不可直接审阅，核验后用 --binary-reviewed 重试", file=sys.stderr)
        return 3
    data["explanations"] = {p: reason for p, reason in explanations.items() if p in changed}
    save(state, data)
    print("范围检查通过；同文件改动仍须逐段核对需求契约。")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("start", help="按方案范围记录当前工作区基线")
    p.add_argument("--repo", required=True)
    p.add_argument("--scope", action="append", required=True,
                   help="文件路径或以 / 结尾的模块目录；可重复")
    p.add_argument("--include", action="append", default=[],
                   help="另行监控一个 Git 忽略的具体文件；可重复")
    p = commands.add_parser("check", help="检查实际差异，越界改动须解释或撤回")
    p.add_argument("--state", required=True)
    p.add_argument("--explain", action="append", default=[],
                   help="仅范围外文件：相对路径=对应需求与必要性")
    p.add_argument("--binary-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        return {"start": start, "check": check}[args.command](args) or 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"范围检查失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
