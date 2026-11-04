#!/usr/bin/env python3
"""Scope gate for a Git worktree: file fingerprints plus mandatory hunk attestation.

State contains hashes of tracked/non-ignored untracked files and baseline copies of
allowlisted files. Store the returned state directory securely; it contains source.
"""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def root_of(path):
    return Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel")).strip()).resolve()


def name(raw):
    return os.fsdecode(raw)


def valid_path(raw):
    path = PurePosixPath(raw)
    if (not raw or raw.startswith("/") or "\\" in raw or "*" in raw or
            "?" in raw or "[" in raw or any(p in ("", ".", "..") for p in raw.split("/"))):
        raise ValueError(f"必须指定具体的仓库相对文件路径: {raw!r}")
    return str(path)


def fingerprint(path):
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            kind, data = "symlink", os.fsencode(os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            kind, data = "file", path.read_bytes()
        else:
            # Submodules and unusual filesystem entries must not silently pass.
            raise ValueError(f"无法核验非常规文件类型: {path}")
        return f"{kind}:{stat.S_IMODE(info.st_mode):o}:{hashlib.sha256(data).hexdigest()}"
    except FileNotFoundError:
        return "absent"


def paths(root):
    raw = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return set(name(p) for p in raw.split(b"\0") if p)


def scan(root, explicit=()):
    # Explicitly allowlisted ignored paths are still part of the baseline.
    return {p: fingerprint(root / p) for p in sorted(paths(root) | set(explicit))}


def index(root):
    # Capture staged edits separately: even if the working tree bytes are restored,
    # changes to the index outside scope are still visible.
    return hashlib.sha256(git(root, "ls-files", "--stage", "-z")).hexdigest(), {
        name(line.split(b"\t", 1)[1]): line.split(b"\t", 1)[0].decode("ascii")
        for line in git(root, "ls-files", "--stage", "-z").split(b"\0") if line
    }


def save(state, manifest):
    temp = state / "manifest.tmp"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    temp.replace(state / "manifest.json")


def load(state):
    return json.loads((state / "manifest.json").read_text(encoding="utf-8"))


def snapshot(state, root, path):
    src = root / path
    dest = state / "baseline" / hashlib.sha256(os.fsencode(path)).hexdigest()
    dest.parent.mkdir(exist_ok=True)
    if src.is_symlink():
        dest.write_bytes(os.fsencode(os.readlink(src)))
    elif src.is_file():
        dest.write_bytes(src.read_bytes())
    elif src.exists():
        raise ValueError(f"不支持非普通文件: {path}")
    else:
        dest.write_bytes(b"")
    return {"file": dest.name, "exists": src.exists() or src.is_symlink(), "symlink": src.is_symlink()}


def start(args):
    root = root_of(args.repo)
    allowed = {valid_path(p): "初始任务范围" for p in args.allow}
    if not allowed:
        raise ValueError("至少提供一个 --allow 具体文件；不得用整个目录放行")
    baseline = scan(root, allowed)
    _, staged = index(root)
    # mkdtemp uses owner-only permissions and lives outside the target repository.
    state = Path(tempfile.mkdtemp(prefix="surgical-dev-gate-"))
    manifest = {"version": 1, "root": str(root), "allowed": allowed,
                "baseline": baseline, "index": staged, "snapshots": {}}
    for p in allowed:
        manifest["snapshots"][p] = snapshot(state, root, p)
    save(state, manifest)
    print(f"状态目录: {state}\n已记录工作区及暂存区基线；按文件逐段复核仍为必需。")


def extend(args):
    state = Path(args.state).resolve()
    manifest = load(state)
    root = Path(manifest["root"])
    p = valid_path(args.allow)
    if not args.reason.strip():
        raise ValueError("扩展范围必须提供对应契约和必要性")
    if p in manifest["allowed"]:
        raise ValueError(f"文件已在范围中: {p}；同文件中新区域在最终差异审阅中说明")
    current = scan(root, [p])
    if current.get(p, "absent") != manifest["baseline"].get(p, "absent"):
        raise ValueError(f"文件已被修改，不能事后放行: {p}；先处理越界修改")
    _, staged = index(root)
    if staged.get(p) != manifest["index"].get(p):
        raise ValueError(f"文件已被暂存修改，不能事后放行: {p}")
    manifest["allowed"][p] = args.reason.strip()
    manifest["snapshots"][p] = snapshot(state, root, p)
    save(state, manifest)
    print(f"已扩展: {p}；理由: {args.reason}")


def show_diff(path, before, after, label):
    if b"\0" in before + after:
        print(f"\n--- {path} ({label}): 二进制差异；须单独检查 ---")
        return True
    try:
        old_lines = before.decode("utf-8").splitlines(keepends=True)
        new_lines = after.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        print(f"\n--- {path} ({label}): 非 UTF-8 差异；须单独检查 ---")
        return True
    lines = difflib.unified_diff(old_lines, new_lines,
                                 fromfile=f"baseline/{path}", tofile=f"{label}/{path}")
    print("".join(lines), end="\n")
    return False


def render_diff(state, root, path, spec, baseline_stage, current_stage):
    old = (state / "baseline" / spec["file"]).read_bytes() if spec["exists"] else b""
    target = root / path
    new = (os.fsencode(os.readlink(target)) if target.is_symlink() else
           target.read_bytes() if target.is_file() else b"")
    print(f"工作区状态: {fingerprint(target)} | 暂存区: {current_stage or '无'}")
    print(f"基线暂存区: {baseline_stage or '无'}")
    nontext = show_diff(path, old, new, "working")
    if current_stage != baseline_stage:
        staged_bytes = git(root, "show", ":" + path) if current_stage else b""
        if staged_bytes != new or old == new:
            print("暂存区与工作区内容不同；额外检查暂存内容:")
            nontext |= show_diff(path, old, staged_bytes, "staged")
    return nontext


def check(args):
    state = Path(args.state).resolve()
    manifest = load(state)
    root = Path(manifest["root"])
    if root_of(root) != root:
        raise ValueError("工作区根目录已改变")
    current = scan(root, manifest["allowed"])
    _, staged = index(root)
    all_paths = set(manifest["baseline"]) | set(current) | set(manifest["index"]) | set(staged)
    changed = sorted(p for p in all_paths if
                     current.get(p, "absent") != manifest["baseline"].get(p, "absent") or
                     staged.get(p) != manifest["index"].get(p))
    outside = [p for p in changed if p not in manifest["allowed"]]
    inside = [p for p in changed if p in manifest["allowed"]]
    review = [(p, current.get(p, "absent"), staged.get(p)) for p in changed]
    digest = hashlib.sha256(json.dumps(review, ensure_ascii=False).encode("utf-8")).hexdigest()
    print("变更文件:", ", ".join(changed) or "无")
    if outside:
        print("越界修改（闸门拒绝）:", ", ".join(outside), file=sys.stderr)
        return 2
    nontext = False
    for p in inside:
        print(f"\n差异审阅: {p} | 原因: {manifest['allowed'][p]}")
        nontext |= render_diff(state, root, p, manifest["snapshots"][p],
                               manifest["index"].get(p), staged.get(p))
    print(f"本次指纹: {digest}")
    if nontext:
        print("存在无法在此显示的差异；请单独检查后加 --binary-reviewed 签核。", file=sys.stderr)
        if not args.binary_reviewed:
            return 3
    if args.attest != digest:
        print("尚未逐段签核，或指纹已过期；闸门拒绝。", file=sys.stderr)
        return 3
    print("范围与指纹检查通过；同文件语义相关性依赖签核者逐段审阅。")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("start", help="在修改前记录工作区与暂存区基线")
    p.add_argument("--repo", required=True)
    p.add_argument("--allow", action="append", required=True)
    p = commands.add_parser("extend", help="在修改新文件前注明必要性并扩展范围")
    p.add_argument("--state", required=True)
    p.add_argument("--allow", required=True)
    p.add_argument("--reason", required=True)
    p = commands.add_parser("check", help="检查范围、展示差异并使用本次指纹签核")
    p.add_argument("--state", required=True)
    p.add_argument("--attest")
    p.add_argument("--binary-reviewed", action="store_true",
                   help="确认已使用其他工具独立检查非文本差异")
    args = parser.parse_args()
    try:
        return {"start": start, "extend": extend, "check": check}[args.command](args) or 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"闸门无法安全核验: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
