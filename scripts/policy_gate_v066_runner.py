#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
policy_gate_v066_runner.py

Runs patch_update_workflow under a strict preview -> gate -> actual sequence.

When the original run is write/deploy capable, the runner first executes a preview
pass with DRY_RUN=true, RUN_NOTION_WRITE=false, RUN_GIT_PUSH=false, validates the
preview/public data through policy_gate_v066.py, then executes the original command.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

WORKFLOW_VERSION = "github_actions_v066"


def truthy(v: str | None) -> bool:
    return str(v or "").lower() in {"1", "true", "yes", "y", "on"}


def run_cmd(cmd: list[str], env: dict[str, str], phase: str) -> int:
    print(f"[v060 runner] phase={phase} command={' '.join(cmd)}", flush=True)
    p = subprocess.run(cmd, env=env)
    print(f"[v060 runner] phase={phase} returncode={p.returncode}", flush=True)
    return int(p.returncode)


def run_gate(mode: str, artifact_dir: str) -> int:
    gate_script = pathlib.Path(__file__).with_name("policy_gate_v066.py")
    cmd = [sys.executable, str(gate_script), "--artifact-dir", artifact_dir, "--mode", mode, "--strict"]
    return run_cmd(cmd, os.environ.copy(), f"gate:{mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")
    args = parser.parse_args()

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("[v060 runner][ERROR] missing command after --", file=sys.stderr)
        return 2

    original_env = os.environ.copy()
    artifact_dir = original_env.get("PATCH_WORKFLOW_ARTIFACT_DIR") or str(pathlib.Path.cwd() / "outputs")
    pathlib.Path(artifact_dir).mkdir(parents=True, exist_ok=True)

    original_dry_run = truthy(original_env.get("DRY_RUN"))
    original_write = truthy(original_env.get("RUN_NOTION_WRITE"))
    original_push = truthy(original_env.get("RUN_GIT_PUSH"))
    needs_prewrite_gate = (not original_dry_run) and (original_write or original_push)

    summary = {
        "workflow_version": WORKFLOW_VERSION,
        "artifact_dir": artifact_dir,
        "needs_prewrite_gate": needs_prewrite_gate,
        "original_dry_run": original_env.get("DRY_RUN"),
        "original_run_notion_write": original_env.get("RUN_NOTION_WRITE"),
        "original_run_git_push": original_env.get("RUN_GIT_PUSH"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if needs_prewrite_gate:
        preview_env = original_env.copy()
        preview_env["DRY_RUN"] = "true"
        preview_env["RUN_NOTION_WRITE"] = "false"
        preview_env["RUN_GIT_PUSH"] = "false"
        preview_env["POLICY_GATE_PHASE"] = "preview"
        preview_rc = run_cmd(cmd, preview_env, "preview")
        summary["preview_returncode"] = preview_rc
        if preview_rc != 0:
            pathlib.Path(artifact_dir, "v060_runner_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return preview_rc

        prewrite_rc = run_gate("pre-write", artifact_dir)
        summary["prewrite_gate_returncode"] = prewrite_rc
        if prewrite_rc != 0:
            pathlib.Path(artifact_dir, "v060_runner_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return prewrite_rc

    actual_env = original_env.copy()
    actual_env["POLICY_GATE_PHASE"] = "actual"
    actual_rc = run_cmd(cmd, actual_env, "actual")
    summary["actual_returncode"] = actual_rc
    if actual_rc != 0:
        pathlib.Path(artifact_dir, "v060_runner_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return actual_rc

    post_rc = run_gate("post-run", artifact_dir)
    summary["post_run_gate_returncode"] = post_rc
    pathlib.Path(artifact_dir, "v060_runner_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return post_rc


if __name__ == "__main__":
    raise SystemExit(main())
