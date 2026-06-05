from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


def _artifact_dir() -> Path:
    return Path(os.environ.get("PATCH_WORKFLOW_ARTIFACT_DIR", "outputs/patch_workflow_artifacts")).resolve()


def _load_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["items", "rows", "data", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _get(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            return " / ".join(str(v) for v in value if v is not None).strip()
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        if text:
            return text
    return ""


def main() -> int:
    art = _artifact_dir()
    art.mkdir(parents=True, exist_ok=True)
    json_path = Path(os.environ.get("PATCH_VIEW_MODEL_JSON", "patch_view_model.json"))
    items = _load_items(json_path)
    rows: list[dict[str, Any]] = []
    for row in items:
        importance = _get(row, "importance")
        patch_category = _get(row, "patch_category", "patchCategory")
        major_update_summary = _get(row, "major_update_summary", "majorUpdateSummary")
        body_summary = _get(row, "body_summary", "bodySummary")
        title = _get(row, "page_title", "title", "항목명")
        game = _get(row, "game", "game_name", "게임명")
        source_url = _get(row, "source_url", "url")
        major_signal = bool(patch_category or major_update_summary or ("신규 대형" in patch_category))
        issues: list[str] = []
        if major_signal and importance != "major":
            issues.append("major_signal_but_importance_not_major")
        if importance == "major" and not major_update_summary:
            issues.append("importance_major_but_major_update_summary_empty")
        if importance == "major" and not patch_category:
            issues.append("importance_major_but_patch_category_empty")
        if not issues:
            continue
        rows.append({
            "game": game,
            "title": title,
            "source_url": source_url,
            "importance": importance,
            "patch_category": patch_category,
            "major_update_summary": major_update_summary,
            "body_summary_preview": body_summary[:240],
            "issues": ";".join(issues),
        })

    json_out = art / "major_consistency_audit.json"
    csv_out = art / "major_consistency_audit.csv"
    json_out.write_text(json.dumps({"count": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["game", "title", "source_url", "importance", "patch_category", "major_update_summary", "body_summary_preview", "issues"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[v038] major consistency audit rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
