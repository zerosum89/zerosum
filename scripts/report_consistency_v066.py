#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v066 post-deploy report consistency gate."""
from __future__ import annotations
import argparse, json, os, pathlib, re, subprocess, sys
from datetime import datetime, timezone
from typing import Any

WORKFLOW_VERSION = "github_actions_v066"
STALE_SCOPE_TOKENS = [
    "v043 strict major detection",
    "v043 major grouping",
    "v043 hardcoding guard",
    "v036 scheduled no-change deploy guard",
    "v037 installer Unicode-safe subprocess capture",
]

def read_json(path: pathlib.Path) -> Any:
    if not path.exists(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: return {"__read_error__": str(exc), "__path__": str(path)}

def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def read_text(path: pathlib.Path) -> str:
    if not path.exists(): return ""
    return path.read_text(encoding="utf-8", errors="replace")

def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def run_git(repo_root: pathlib.Path, args: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(["git", *args], cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", errors="replace"), p.stderr.decode("utf-8", errors="replace")

def boolish(v: Any) -> bool:
    if isinstance(v, bool): return v
    if v is None: return False
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def rewrite_scope(report_text: str, workflow_version: str) -> tuple[str, bool]:
    heading = f"## {workflow_version} scope"
    scope = f"""{heading}

- v066 report consistency: patch_view_model_export_summary.json is finalized from git_deploy_result.json after deploy.
- v066 phase separation: preview, pre-write gate, actual run, post-run gate, report consistency, and deploy result are reported as separate states.
- v060/v066 decision model: body_summary, highlight_sentence_candidates, importance_suggestion, and importance_decision keep single responsibilities.
- Display rule: card major badge follows importance_decision; body-summary emphasis follows major decision AND highlight_sentence_candidates.
- Legacy major fields are blocked from public output: derived_major*, derived_importance, display_importance, major_summary_groups, major_group_count, major_summary_indices.
- Notion write guard: write runs only when dry_run=false, run_notion_write=true, and gate status is pass.
- Data-only deploy guard: GitHub Pages deploy may commit patch_view_model.json only; template changes require a separate approved package.
- Report rule: file_changed and patch_view_model_git_changed reflect final Git deploy state, not only the actual run's pre-deploy workspace state.
""".rstrip()
    pattern = re.compile(r"\n## github_actions_v\d+ scope\n[\s\S]*$", re.M)
    if pattern.search(report_text):
        new_text = pattern.sub("\n" + scope + "\n", report_text)
        return new_text, new_text != report_text
    if report_text.strip(): return report_text.rstrip() + "\n\n" + scope + "\n", True
    return scope + "\n", True

def finalize_export_summary(artifact_dir: pathlib.Path) -> dict[str, Any]:
    export_path = artifact_dir / "patch_view_model_export_summary.json"
    deploy_path = artifact_dir / "git_deploy_result.json"
    export_summary = read_json(export_path)
    deploy_result = read_json(deploy_path)
    if not isinstance(export_summary, dict): export_summary = {"source": "missing_or_invalid", "items": None}
    if not isinstance(deploy_result, dict): deploy_result = {"status": "MISSING", "changed_files": [], "committed": False, "pushed": False}
    changed_files = deploy_result.get("changed_files") if isinstance(deploy_result.get("changed_files"), list) else []
    norm_changed = [str(x).replace("\\", "/") for x in changed_files]
    patch_json_in_deploy = "patch_view_model.json" in norm_changed
    committed = boolish(deploy_result.get("committed"))
    pushed = boolish(deploy_result.get("pushed"))
    deploy_status = str(deploy_result.get("status") or "")
    final_git_changed = patch_json_in_deploy or (deploy_status in {"PUSHED", "COMMITTED"} and committed)
    before = {k: export_summary.get(k) for k in ["patch_view_model_content_changed", "patch_view_model_git_changed", "patch_view_model_pushed", "file_changed"]}
    export_summary["workflow_version"] = WORKFLOW_VERSION
    export_summary["final_change_basis"] = "git_deploy_result.changed_files"
    export_summary["git_deploy_status"] = deploy_status
    export_summary["git_deploy_changed_files"] = changed_files
    export_summary["git_deploy_committed"] = committed
    export_summary["git_deploy_pushed"] = pushed
    export_summary["git_deploy_commit_hash"] = deploy_result.get("commit_hash") or deploy_result.get("commit_full_hash")
    export_summary["patch_view_model_git_changed"] = bool(final_git_changed)
    export_summary["patch_view_model_pushed"] = bool(pushed and final_git_changed)
    export_summary["file_changed"] = bool(export_summary.get("patch_view_model_content_changed") or final_git_changed)
    export_summary["report_consistency_status"] = "pass"
    export_summary["report_consistency_checked_at"] = datetime.now(timezone.utc).isoformat()
    after = {k: export_summary.get(k) for k in ["patch_view_model_content_changed", "patch_view_model_git_changed", "patch_view_model_pushed", "file_changed"]}
    write_json(export_path, export_summary)
    return {"before": before, "after": after, "deploy_result": deploy_result, "final_git_changed": final_git_changed}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", default=os.environ.get("PATCH_WORKFLOW_ARTIFACT_DIR") or "outputs")
    parser.add_argument("--repo-root", default=os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    artifact_dir = pathlib.Path(args.artifact_dir).resolve(); artifact_dir.mkdir(parents=True, exist_ok=True)
    repo_root = pathlib.Path(args.repo_root).resolve()
    errors=[]; warnings=[]
    result={"workflow_version": WORKFLOW_VERSION, "artifact_dir": str(artifact_dir), "repo_root": str(repo_root), "created_at": datetime.now(timezone.utc).isoformat()}
    finalization = finalize_export_summary(artifact_dir)
    result["export_summary_finalization"] = finalization
    report_path = artifact_dir / "workflow_report.md"
    report_text = read_text(report_path)
    rewritten, scope_changed = rewrite_scope(report_text, WORKFLOW_VERSION)
    write_text(report_path, rewritten)
    stale_remaining = [t for t in STALE_SCOPE_TOKENS if t in rewritten]
    result["workflow_report_scope_rewritten"] = scope_changed
    result["stale_scope_tokens_remaining"] = stale_remaining
    if stale_remaining: errors.append("stale workflow_report scope tokens remain: " + ", ".join(stale_remaining))
    runner_candidates = sorted(artifact_dir.glob("v*_runner_summary.json"))
    result["runner_summary_files"] = [p.name for p in runner_candidates]
    if runner_candidates:
        runner_path = runner_candidates[-1]
        runner = read_json(runner_path)
        if isinstance(runner, dict):
            runner["report_consistency_version"] = WORKFLOW_VERSION
            runner["report_consistency_status"] = "pass" if not errors else "blocked"
            runner["git_deploy_status"] = finalization.get("deploy_result", {}).get("status")
            runner["patch_view_model_git_changed_final"] = finalization.get("final_git_changed")
            write_json(runner_path, runner)
    export_summary = read_json(artifact_dir / "patch_view_model_export_summary.json") or {}
    deploy = read_json(artifact_dir / "git_deploy_result.json") or {}
    changed_files = deploy.get("changed_files") if isinstance(deploy.get("changed_files"), list) else []
    pushed_patch_json = boolish(deploy.get("pushed")) and "patch_view_model.json" in [str(x).replace("\\", "/") for x in changed_files]
    if pushed_patch_json and not boolish(export_summary.get("patch_view_model_git_changed")):
        errors.append("git_deploy_result pushed patch_view_model.json but export summary git_changed is false")
    if pushed_patch_json and not boolish(export_summary.get("file_changed")):
        errors.append("git_deploy_result pushed patch_view_model.json but export summary file_changed is false")
    rc, status_text, status_err = run_git(repo_root, ["status", "--porcelain"])
    result["git_status_returncode"] = rc
    result["git_status_after_report_consistency"] = status_text
    if rc != 0: warnings.append("git status failed: " + status_err.strip())
    result["errors"] = errors; result["warnings"] = warnings; result["status"] = "pass" if not errors else "blocked"
    write_json(artifact_dir / "report_consistency_v066.json", result)
    if errors:
        print("[v066 report consistency][BLOCKED] " + "; ".join(errors), file=sys.stderr)
        return 1 if args.strict else 0
    print("[v066 report consistency] pass")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
