#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package Release Gate v079.

Reusable validator for generated local execution packages in the patch-update workflow.
It checks that a package is structurally runnable before it is handed to a user.

This script intentionally does not call Notion, GitHub push, or mutate repo data.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional

WORKFLOW_VERSION = "github_actions_v079"
GATE_VERSION = "package_release_gate_v079"

REQUIRED_DIRS = ["scripts", "inputs", "outputs", "outputs/deliverables"]
REQUIRED_FILES = ["01_RUN.cmd", "01_RUN.sh"]
DEFAULT_FORBIDDEN_ARCHIVE_PARTS = [
    "__pycache__",
    ".pyc",
    ".DS_Store",
    "Thumbs.db",
]

@dataclass
class GateFinding:
    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _run_bytes(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _syntax_check_py(py_files: Iterable[Path]) -> list[GateFinding]:
    findings: list[GateFinding] = []
    for path in py_files:
        try:
            source = _read_text(path)
            compile(source, str(path), "exec")
        except Exception as exc:  # noqa: BLE001
            findings.append(GateFinding("error", "PY_SYNTAX_ERROR", f"Python syntax check failed: {exc}", str(path)))
    return findings


def _delivery_open_check(run_cmd: str, run_sh: str) -> list[GateFinding]:
    findings: list[GateFinding] = []
    cmd_l = run_cmd.lower()
    sh_l = run_sh.lower()
    if "explorer" not in cmd_l:
        findings.append(GateFinding("error", "RUN_CMD_NO_EXPLORER", "01_RUN.cmd must open outputs\\deliverables after execution.", "01_RUN.cmd"))
    if not any(token in sh_l for token in ["open ", "xdg-open", "explorer.exe"]):
        findings.append(GateFinding("warning", "RUN_SH_NO_OPEN", "01_RUN.sh should open outputs/deliverables when possible.", "01_RUN.sh"))
    return findings


def _dangerous_write_push_check(package_root: Path, allow_git_push: bool, allow_notion_write: bool) -> list[GateFinding]:
    findings: list[GateFinding] = []
    scan_ext = {".py", ".cmd", ".sh", ".ps1", ".yml", ".yaml"}
    for path in package_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in scan_ext:
            continue
        rel = path.relative_to(package_root).as_posix()
        text = _read_text(path).lower()
        # Detect executable git push, not policy text mentioning the phrase.
        actual_git_push = bool(
            re.search(r"(?m)^\s*(?:git|&\s*git)\s+push\b", text)
            or re.search(r"\[\s*['\"]git['\"]\s*,\s*['\"]push['\"]", text)
            or re.search(r"subprocess\.[a-z_]+\([^\)]*git[^\)]*push", text)
        )
        if not allow_git_push and actual_git_push:
            findings.append(GateFinding("error", "UNDECLARED_GIT_PUSH", "Executable git push appears in package but allow_git_push=false.", rel))
        # Heuristic only. Direct Notion page mutation must be declared.
        actual_notion_write = bool(re.search(r"\bpages\.(create|update)\s*\(", text))
        if not allow_notion_write and actual_notion_write:
            findings.append(GateFinding("warning", "POSSIBLE_NOTION_WRITE", "Possible Notion page mutation found. Verify package write scope.", rel))
    return findings


def _zip_integrity(zip_path: Path, expected_root: Optional[str], min_entries: int) -> tuple[list[GateFinding], dict[str, Any]]:
    findings: list[GateFinding] = []
    meta: dict[str, Any] = {"zip_path": str(zip_path), "exists": zip_path.exists()}
    if not zip_path.exists():
        return [GateFinding("error", "ZIP_NOT_FOUND", "Package zip not found.", str(zip_path))], meta
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            entries = zf.namelist()
            meta.update({"entry_count": len(entries), "size_bytes": zip_path.stat().st_size, "bad_entry": bad})
            if bad:
                findings.append(GateFinding("error", "ZIP_TESTZIP_FAILED", f"Corrupt zip entry: {bad}", bad))
            if len(entries) < min_entries:
                findings.append(GateFinding("error", "ZIP_TOO_FEW_ENTRIES", f"ZIP entry count {len(entries)} < required {min_entries}.", str(zip_path)))
            if expected_root:
                root_prefix = expected_root.rstrip("/") + "/"
                bad_roots = [e for e in entries if e and not e.startswith(root_prefix)]
                if bad_roots:
                    findings.append(GateFinding("error", "ZIP_ROOT_MISMATCH", "ZIP entries must be under the root folder matching ZIP filename.", bad_roots[0]))
            for part in DEFAULT_FORBIDDEN_ARCHIVE_PARTS:
                hits = [e for e in entries if part in e]
                if hits:
                    findings.append(GateFinding("error", "FORBIDDEN_ARCHIVE_ENTRY", f"Forbidden archive entry contains {part}.", hits[0]))
    except zipfile.BadZipFile as exc:
        findings.append(GateFinding("error", "BAD_ZIP", f"Cannot open zip: {exc}", str(zip_path)))
    return findings, meta


def validate_package(package_root: Path, package_zip: Optional[Path] = None, allow_git_push: bool = False, allow_notion_write: bool = False, min_zip_entries: int = 8) -> dict[str, Any]:
    package_root = package_root.resolve()
    findings: list[GateFinding] = []
    if not package_root.exists():
        findings.append(GateFinding("error", "PACKAGE_ROOT_NOT_FOUND", "Package root not found.", str(package_root)))
    else:
        for rel in REQUIRED_DIRS:
            if not (package_root / rel).exists():
                findings.append(GateFinding("error", "REQUIRED_DIR_MISSING", f"Required directory missing: {rel}", rel))
        for rel in REQUIRED_FILES:
            if not (package_root / rel).is_file():
                findings.append(GateFinding("error", "REQUIRED_FILE_MISSING", f"Required file missing: {rel}", rel))
        if (package_root / "01_RUN.cmd").is_file() and (package_root / "01_RUN.sh").is_file():
            findings.extend(_delivery_open_check(_read_text(package_root / "01_RUN.cmd"), _read_text(package_root / "01_RUN.sh")))
        py_files = list((package_root / "scripts").glob("*.py")) if (package_root / "scripts").exists() else []
        findings.extend(_syntax_check_py(py_files))
        findings.extend(_dangerous_write_push_check(package_root, allow_git_push, allow_notion_write))
    zip_meta: dict[str, Any] = {}
    if package_zip:
        zf, zip_meta = _zip_integrity(package_zip.resolve(), package_zip.stem, min_zip_entries)
        findings.extend(zf)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    return {
        "workflow_version": WORKFLOW_VERSION,
        "gate_version": GATE_VERSION,
        "package_root": str(package_root),
        "package_zip": str(package_zip.resolve()) if package_zip else None,
        "status": "pass" if not errors else "blocked",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": [f.to_dict() for f in findings],
        "zip_meta": zip_meta,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-root", required=True)
    ap.add_argument("--package-zip")
    ap.add_argument("--allow-git-push", action="store_true")
    ap.add_argument("--allow-notion-write", action="store_true")
    ap.add_argument("--min-zip-entries", type=int, default=8)
    ap.add_argument("--out-json")
    ap.add_argument("--out-csv")
    args = ap.parse_args()
    result = validate_package(
        Path(args.package_root),
        Path(args.package_zip) if args.package_zip else None,
        allow_git_push=args.allow_git_push,
        allow_notion_write=args.allow_notion_write,
        min_zip_entries=args.min_zip_entries,
    )
    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.out_csv:
        out = Path(args.out_csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["severity", "code", "message", "path"])
            w.writeheader()
            for row in result["findings"]:
                w.writerow(row)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
