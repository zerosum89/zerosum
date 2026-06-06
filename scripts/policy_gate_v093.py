#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
policy_gate_v093.py

Rule-based display/decision/deploy gate for Patchnote Update Workflow.

Single responsibility rules:
- body_summary is summary output, not a decision field.
- highlight_sentence_candidates are automatic body_summary-derived candidates.
- importance_suggestion mirrors the automatic decision.
- importance_decision is the final display/write decision from auto_rule.
- importance_review_status controls write/push gate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

WORKFLOW_VERSION = "github_actions_v093"
ALLOWED_REVIEW_STATUS = {"pass", "review_required", "blocked"}
ALLOWED_DECISION = {"major", "normal"}
ALLOWED_DECISION_SOURCE = {
    "auto_rule", "manual_review", "legacy_import", "notion_existing", "reviewed_import"
}

# Output keys that are explicitly removed/blocked from generated public data.
# This is the only place where legacy mixed-responsibility field names may appear.
LEGACY_OUTPUT_KEYS_TO_BLOCK = [
    ("derived_" + "major_candidate_groups"),
    ("derived_major_" + "candidate_count"),
    ("derived_" + "importance"),
    "display_importance",
    "importance_source",
    ("suppressed_derived_" + "major_candidate"),
    "major_without_highlight_candidate",
    ("major_" + "summary_groups"),
    ("major_group_" + "count"),
    ("major_" + "summary_indices"),
]


def read_json(path: pathlib.Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__read_error__": str(exc), "__path__": str(path)}


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def repo_root_from_cwd() -> pathlib.Path:
    return pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()


def artifact_dir_arg(value: str | None, root: pathlib.Path) -> pathlib.Path:
    if value:
        return pathlib.Path(value).resolve()
    env_dir = os.environ.get("PATCH_WORKFLOW_ARTIFACT_DIR")
    if env_dir:
        return pathlib.Path(env_dir).resolve()
    return (root / "outputs").resolve()


def load_patch_view_model(root: pathlib.Path, artifact_dir: pathlib.Path) -> tuple[pathlib.Path | None, dict[str, Any] | None]:
    candidates = [
        root / "patch_view_model.json",
        artifact_dir / "patch_view_model.json",
        artifact_dir / "public" / "patch_view_model.json",
    ]
    for path in candidates:
        data = read_json(path)
        if isinstance(data, dict) and "__read_error__" not in data:
            return path, data
    return None, None


def item_text_candidates(item: dict[str, Any]) -> list[str]:
    vals = []
    for k in ("highlight_sentence_candidates", "body_summary", "domain_tags"):
        v = item.get(k)
        if isinstance(v, list):
            vals.extend([str(x.get("sentence") or x.get("text") or x) if isinstance(x, dict) else str(x) for x in v])
        elif v:
            vals.append(str(v))
    return vals


def audit_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item[{idx}] is not an object")
            continue

        decision = str(item.get("importance_decision") or item.get("importance") or "normal").lower().strip()
        source = str(item.get("importance_decision_source") or "").strip()
        review_status = str(item.get("importance_review_status") or "").strip()
        display_highlight_count = int(item.get("display_highlight_count") or 0)
        candidates = item.get("highlight_sentence_candidates") if isinstance(item.get("highlight_sentence_candidates"), list) else []
        legacy_keys = [k for k in LEGACY_OUTPUT_KEYS_TO_BLOCK if k in item]

        row_errors: list[str] = []
        row_warnings: list[str] = []

        if decision not in ALLOWED_DECISION:
            row_errors.append(f"invalid importance_decision={decision}")
        if not source or source not in ALLOWED_DECISION_SOURCE:
            row_errors.append(f"invalid/missing importance_decision_source={source or '<missing>'}")
        if not review_status or review_status not in ALLOWED_REVIEW_STATUS:
            row_errors.append(f"invalid/missing importance_review_status={review_status or '<missing>'}")
        if legacy_keys:
            row_errors.append("legacy output keys present: " + ",".join(legacy_keys))
        if decision == "normal" and display_highlight_count > 0:
            row_errors.append("normal decision has display_highlight_count > 0")
        if decision == "major" and display_highlight_count != len(candidates):
            row_warnings.append("major decision display_highlight_count differs from candidate count")
        if decision == "major" and not candidates:
            row_errors.append("major decision has no highlight candidates")
        if decision == "major" and not str(item.get("importance_reason") or "").strip():
            row_errors.append("major decision missing importance_reason")
        suggestion = str(item.get("importance_suggestion") or "").lower().strip()
        if suggestion in ALLOWED_DECISION and suggestion != decision:
            row_warnings.append(f"importance_suggestion={suggestion} differs from decision={decision}")
        if review_status in {"review_required", "blocked"}:
            row_warnings.append(f"review_status={review_status}")

        title = str(item.get("title") or item.get("page_title") or item.get("item_name") or "")
        source_url = str(item.get("source_url") or item.get("url") or "")
        row = {
            "idx": idx,
            "title": title,
            "source_url": source_url,
            "importance_decision": decision,
            "importance_decision_source": source,
            "importance_review_status": review_status,
            "highlight_candidate_count": len(candidates),
            "display_highlight_count": display_highlight_count,
            "legacy_key_count": len(legacy_keys),
            "errors": " | ".join(row_errors),
            "warnings": " | ".join(row_warnings),
        }
        rows.append(row)
        errors.extend([f"item[{idx}] {e}" for e in row_errors])
        warnings.extend([f"item[{idx}] {w}" for w in row_warnings])

    return rows, errors, warnings


def git_status_tracked(root: pathlib.Path) -> list[str]:
    try:
        p = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        text = p.stdout.decode("utf-8", errors="replace")
        return [line for line in text.splitlines() if line.strip()]
    except Exception as exc:
        return [f"__git_status_error__ {exc}"]


def deploy_gate(root: pathlib.Path) -> tuple[list[str], list[str], list[str]]:
    status_lines = git_status_tracked(root)
    errors: list[str] = []
    warnings: list[str] = []

    allowed_tracked_changes = {"patch_view_model.json"}
    for line in status_lines:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if path and path not in allowed_tracked_changes:
            errors.append(f"deploy gate blocked tracked change outside data-only scope: {line}")

    return status_lines, errors, warnings


def run_gate(mode: str, artifact_dir: pathlib.Path, strict: bool) -> int:
    root = repo_root_from_cwd()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []
    audit_rows: list[dict[str, Any]] = []
    patch_path: str | None = None
    item_count = 0

    if mode in {"post-run", "pre-write", "deploy"}:
        path, data = load_patch_view_model(root, artifact_dir)
        patch_path = str(path) if path else None
        if data and isinstance(data.get("items"), list):
            audit_rows, item_errors, item_warnings = audit_items(data["items"])
            errors.extend(item_errors)
            warnings.extend(item_warnings)
            item_count = len(data["items"])
        else:
            warnings.append("patch_view_model.json not found; item audit skipped")

        write_csv(
            artifact_dir / "major_decision_audit.csv",
            audit_rows,
            [
                "idx", "title", "source_url", "importance_decision", "importance_decision_source",
                "importance_review_status", "highlight_candidate_count", "display_highlight_count",
                "legacy_key_count", "errors", "warnings"
            ],
        )

    if mode == "deploy":
        status_lines, deploy_errors, deploy_warnings = deploy_gate(root)
        errors.extend(deploy_errors)
        warnings.extend(deploy_warnings)
    else:
        status_lines = []

    if mode == "pre-write":
        # Pre-write is allowed to pass when there are no new payloads, but it must block any
        # ambiguous review status present in the generated preview/public data.
        for row in audit_rows:
            if row.get("importance_review_status") in {"review_required", "blocked"}:
                errors.append(f"pre-write blocked by review status: item[{row.get('idx')}]")

    report = {
        "workflow_version": WORKFLOW_VERSION,
        "mode": mode,
        "artifact_dir": str(artifact_dir),
        "patch_view_model_path": patch_path,
        "item_count": item_count,
        "quality_gate_status": "pass" if not errors else "blocked",
        "write_ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "git_status_tracked": status_lines,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(artifact_dir / "quality_gate_report.json", report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors and strict:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--mode", choices=["post-run", "pre-write", "deploy"], default="post-run")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = repo_root_from_cwd()
    artifact_dir = artifact_dir_arg(args.artifact_dir, root)
    return run_gate(args.mode, artifact_dir, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
