#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a skill zip and a per-file SHA-256 manifest from the working tree.

The release flow uses ``git archive`` for committed trees.  This helper is
intentionally different: it packages tracked *and* uncommitted files so a skill
can be tested from a dirty checkout.  ``dist/``, caches and VCS metadata are
excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".zip", ".tmp", ".bak"}


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def _git_paths() -> List[str]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version() -> str:
    text = (ROOT / "engine" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("cannot find __version__ in engine/__init__.py")
    return match.group(1)


def _is_excluded(relative: str, extra_paths: Iterable[str]) -> bool:
    if relative in set(extra_paths):
        return True
    parts = PurePosixPath(relative).parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    if relative.endswith(tuple(EXCLUDED_SUFFIXES)):
        return True
    return False


def _source_repository() -> str:
    try:
        remote = _git("config", "--get", "remote.origin.url")
    except subprocess.CalledProcessError:
        return ""
    if remote.startswith("git@github.com:"):
        remote = "https://github.com/" + remote[len("git@github.com:") :]
    if remote.endswith(".git"):
        remote = remote[:-4]
    return remote


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build(output: Path, manifest_path: Path, version: str, force: bool) -> dict:
    if output.exists() and not force:
        raise FileExistsError("%s already exists (use --force to replace)" % output)

    output_relative = _display_path(output)
    manifest_relative = _display_path(manifest_path)
    files = [
        item
        for item in _git_paths()
        if (ROOT / item).is_file()
        and not _is_excluded(item, (output_relative, manifest_relative))
    ]
    files.sort(key=str.casefold)
    if "SKILL.md" not in files:
        raise RuntimeError("SKILL.md is missing from the package")

    directories = sorted(
        {
            str(PurePosixPath(item).parent)
            for item in files
            if str(PurePosixPath(item).parent) != "."
        },
        key=str.casefold,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for directory in directories:
            archive.writestr(directory + "/", b"")
        for relative in files:
            archive.write(ROOT / relative, arcname=relative)

    archive_bytes = output.read_bytes()
    manifest = {
        "package_name": "officecli-template-filler",
        "version": version,
        "source_repository": _source_repository(),
        "source_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "source_commit": _git("rev-parse", "HEAD"),
        "source_commit_subject": _git("log", "-1", "--pretty=%s"),
        "source_dirty": bool(_git("status", "--porcelain")),
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "build_tool": "scripts/package_skill.py (working tree)",
        "archive": {
            "path": output_relative,
            "format": "zip",
            "size_bytes": len(archive_bytes),
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "file_count": len(files),
            "zip_entry_count_including_directories": len(directories) + len(files),
        },
        "files": [
            {
                "path": relative,
                "size_bytes": (ROOT / relative).stat().st_size,
                "sha256": _sha256(ROOT / relative),
            }
            for relative in files
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="Package version (default: engine.__version__)")
    parser.add_argument("--output", default="", help="Zip output path")
    parser.add_argument("--manifest", default="", help="Manifest output path")
    parser.add_argument("--force", action="store_true", help="Replace existing outputs")
    args = parser.parse_args()

    version = args.version or _version()
    output = (
        Path(args.output)
        if args.output
        else ROOT / "dist" / ("officecli-template-filler-v%s.zip" % version)
    )
    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else output.with_suffix(".manifest.json")
    )
    manifest = build(output.resolve(), manifest_path.resolve(), version, args.force)
    print(json.dumps({
        "archive": manifest["archive"]["path"],
        "sha256": manifest["archive"]["sha256"],
        "files": manifest["archive"]["file_count"],
        "manifest": manifest_path.resolve().as_posix(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("PACKAGE_FAILED: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
