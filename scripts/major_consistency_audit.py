from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

AUDIT_VERSION = "github_actions_v039"
HIGHLIGHT_POLICY = "sentence_unit: body_summary lines are highlighted when they match major_update_summary or representative_signals tokens. Card major state remains controlled only by importance=major."

STOP_TOKENS = {"신규", "대형", "추가", "변경", "개선", "콘텐츠", "업데이트", "패치", "안내", "주요", "보상"}


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


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " / ".join(_stringify(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _get(row: dict[str, Any], *keys: str) -> str:
    raw = row.get("raw_properties") if isinstance(row.get("raw_properties"), dict) else {}
    for key in keys:
        for src in (row, raw):
            value = src.get(key)
            text = _stringify(value)
            if text:
                return text
    return ""


def _lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_stringify(v).strip() for v in value if _stringify(v).strip()]
    text = _stringify(value).replace("\r", "")
    if not text:
        return []
    # Preserve explicit line-based summaries, but split slash-joined list values only when no newline exists.
    if "\n" in text:
        return [x.strip() for x in text.split("\n") if x.strip()]
    return [x.strip() for x in re.split(r"\s*/\s*(?=[^/]+:)", text) if x.strip()]


def _tokens(*values: Any) -> list[str]:
    source = " ".join(_stringify(v) for v in values if _stringify(v))
    tokens = []
    seen = set()
    for token in re.split(r"[^0-9A-Za-z가-힣]+", source):
        token = token.strip()
        if len(token) < 3 or token in STOP_TOKENS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _highlight_lines(body_lines: list[str], major_update_summary: str, representative_signals: str) -> list[str]:
    tokens = _tokens(major_update_summary, representative_signals)
    if not tokens:
        return []
    out = []
    for line in body_lines:
        if any(token in line for token in tokens):
            out.append(line)
    return out


def main() -> int:
    art = _artifact_dir()
    art.mkdir(parents=True, exist_ok=True)
    json_path = Path(os.environ.get("PATCH_VIEW_MODEL_JSON", "patch_view_model.json"))
    items = _load_items(json_path)
    rows: list[dict[str, Any]] = []
    issue_count = 0
    for row in items:
        importance = _get(row, "importance", "중요도", "Importance").lower() or "normal"
        patch_category = _get(row, "patch_category", "patchCategory", "패치 카테고리")
        major_update_summary = _get(row, "major_update_summary", "majorUpdateSummary", "main_updates", "주요 업데이트", "주요 업데이트 요약")
        body_summary = _get(row, "body_summary", "bodySummary", "본문 요약")
        representative_signals = _get(row, "representative_signals", "signals", "대표 핵심 신호")
        title = _get(row, "page_title", "title", "항목명")
        game = _get(row, "game", "game_name", "게임명")
        source_url = _get(row, "source_url", "url", "원문 URL")
        body_lines = _lines(row.get("body_summary") or row.get("bodySummary") or body_summary)
        highlight_lines = _highlight_lines(body_lines, major_update_summary, representative_signals)

        card_major = importance == "major"
        body_sentence_highlight = len(highlight_lines) > 0
        major_signal = bool(patch_category or major_update_summary or ("신규 대형" in patch_category))

        issues: list[str] = []
        if major_signal and not card_major:
            issues.append("major_signal_but_importance_not_major")
        if card_major and not major_update_summary:
            issues.append("importance_major_but_major_update_summary_empty")
        if card_major and not patch_category:
            issues.append("importance_major_but_patch_category_empty")
        if card_major and not body_sentence_highlight:
            issues.append("card_major_but_no_body_highlight_candidate")
        if body_sentence_highlight and not major_signal:
            issues.append("body_highlight_without_major_signal")

        if not (issues or card_major or body_sentence_highlight):
            continue
        if issues:
            issue_count += 1

        rows.append({
            "game": game,
            "title": title,
            "source_url": source_url,
            "importance": importance,
            "card_major": card_major,
            "body_sentence_highlight": body_sentence_highlight,
            "highlight_line_count": len(highlight_lines),
            "highlight_policy": HIGHLIGHT_POLICY,
            "patch_category": patch_category,
            "major_update_summary": major_update_summary,
            "highlight_lines_preview": " / ".join(highlight_lines[:5]),
            "body_summary_preview": body_summary[:240],
            "issues": ";".join(issues),
        })

    payload = {
        "audit_version": AUDIT_VERSION,
        "count": len(rows),
        "issue_count": issue_count,
        "highlight_policy": HIGHLIGHT_POLICY,
        "rows": rows,
    }
    json_out = art / "major_consistency_audit.json"
    csv_out = art / "major_consistency_audit.csv"
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = [
        "game", "title", "source_url", "importance", "card_major", "body_sentence_highlight",
        "highlight_line_count", "highlight_policy", "patch_category", "major_update_summary",
        "highlight_lines_preview", "body_summary_preview", "issues",
    ]
    with csv_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[v039] major/highlight consistency audit rows={len(rows)} issues={issue_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
