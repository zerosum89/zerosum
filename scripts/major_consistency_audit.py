from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

AUDIT_VERSION = "github_actions_v040"
HIGHLIGHT_POLICY = (
    "major_group: body_summary update-units are first classified as major types; "
    "multiple major units of the same type are grouped into one red summary sentence. "
    "Card major state is derived from major_group_count >= 1."
)

MAJOR_TYPE_ORDER = [
    "new_pve_content",
    "new_pvp_war",
    "new_growth_axis",
    "class_skill_system",
    "server_world_structure",
    "economy_crafting_system",
    "major_rule_rework",
]


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
    if "\n" in text:
        return [x.strip() for x in text.split("\n") if x.strip()]
    return [x.strip() for x in re.split(r"\s*/\s*(?=[^/]+:)", text) if x.strip()]


def clean_line(line: Any) -> str:
    return re.sub(r"^[-•*]\s*", "", str(line or "").strip()).strip()


def domain(line: str) -> str:
    return line.split(":", 1)[0].strip() if ":" in line else ""


def has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def major_type_for_line(line: str) -> str | None:
    text = clean_line(line)
    d = domain(text)
    is_event_or_bm = d.startswith(("이벤트", "이벤트/보상", "상점/BM", "상점", "보상"))
    bm_major = has_any(text, ["수집 효과", "능력치", "성장축", "전용 장비", "아이템 수집", "제작 구조", "거래 구조"])
    if is_event_or_bm and not bm_major:
        return None
    if "PvP" in d or has_any(text, ["공성", "수성", "전쟁", "점령", "쟁탈", "서버 침공", "전장", "월드 던전", "경쟁 콘텐츠"]):
        return "new_pvp_war"
    if "클래스" in d or has_any(text, ["클래스", "전직", "스킬", "태세"]):
        return "class_skill_system"
    if "서버" in d or has_any(text, ["서버 이전", "서버 통합", "신규 서버", "월드군", "서버군"]):
        return "server_world_structure"
    if "성장" in d or "장비" in d or has_any(text, ["성장 시스템", "방어구", "무기 형상", "유물", "능력치", "스테이터스", "강화", "각성", "아이템 수집", "도감", "전용 장비"]):
        return "new_growth_axis"
    if "경제" in d or "거래" in d or has_any(text, ["제작", "거래소", "재화", "교환 구조", "경제"]):
        return "economy_crafting_system"
    if "PvE" in d or has_any(text, ["챕터", "지역", "던전", "보스", "레이드", "성채", "탑", "퀘스트", "대륙"]):
        return "new_pve_content"
    if has_any(text, ["개편", "구조", "규칙", "보상 구조", "진행 구조"]):
        return "major_rule_rework"
    return None


def derive_groups(body_lines: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(body_lines):
        line = clean_line(raw)
        mtype = major_type_for_line(line)
        if not mtype:
            continue
        g = grouped.setdefault(mtype, {"major_type": mtype, "source_unit_indices": [], "source_unit_count": 0})
        g["source_unit_indices"].append(idx)
        g["source_unit_count"] += 1
    return [grouped[t] for t in MAJOR_TYPE_ORDER if t in grouped]


def main() -> int:
    art = _artifact_dir()
    art.mkdir(parents=True, exist_ok=True)
    json_path = Path(os.environ.get("PATCH_VIEW_MODEL_JSON", "patch_view_model.json"))
    items = _load_items(json_path)

    rows: list[dict[str, Any]] = []
    issue_count = 0
    review_count = 0
    for row in items:
        title = _get(row, "page_title", "title", "항목명")
        game = _get(row, "game", "game_name", "게임명")
        source_url = _get(row, "source_url", "url", "원문 URL")
        importance = (_get(row, "importance", "중요도", "Importance") or "normal").lower()
        display_importance = (_get(row, "display_importance", "derived_importance") or "").lower()
        body_lines = _lines(row.get("body_summary") or row.get("bodySummary") or _get(row, "body_summary", "본문 요약"))
        stored_groups = row.get("major_summary_groups") if isinstance(row.get("major_summary_groups"), list) else []
        groups = stored_groups or derive_groups(body_lines)
        major_group_count = int(row.get("major_group_count") or len(groups) or 0)
        card_major = (display_importance == "major") or (major_group_count >= 1)
        derived_major = len(groups) >= 1
        red_line_count = len(groups)
        source_unit_total = sum(int(g.get("source_unit_count") or len(g.get("source_unit_indices") or [])) for g in groups if isinstance(g, dict))
        event_bm_only = bool(groups) and all(major_type_for_line(body_lines[i]) is None for i in range(len(body_lines)) if False)

        issues: list[str] = []
        reviews: list[str] = []
        if derived_major and not card_major:
            issues.append("major_group_exists_but_card_major_false")
        if card_major and not derived_major:
            issues.append("card_major_true_but_major_group_missing")
        if major_group_count != len(groups):
            issues.append("major_group_count_mismatch")
        if red_line_count > 3:
            reviews.append("major_group_count_over_3")
        if body_lines and red_line_count >= len(body_lines):
            reviews.append("all_body_lines_would_be_highlighted")
        if source_unit_total > red_line_count and red_line_count == source_unit_total:
            reviews.append("major_units_not_grouped")
        if importance == "major" and not derived_major:
            reviews.append("legacy_importance_major_but_derived_normal")
        if importance != "major" and derived_major:
            reviews.append("legacy_importance_normal_but_derived_major")

        if issues:
            issue_count += 1
        if reviews:
            review_count += 1
        if not (issues or reviews or card_major or derived_major):
            continue

        rows.append({
            "game": game,
            "title": title,
            "source_url": source_url,
            "legacy_importance": importance,
            "display_importance": display_importance or ("major" if derived_major else "normal"),
            "card_major": card_major,
            "derived_major": derived_major,
            "major_group_count": len(groups),
            "major_source_unit_total": source_unit_total,
            "major_types": " / ".join(str(g.get("major_type", "")) for g in groups if isinstance(g, dict)),
            "major_group_text_preview": " / ".join(str(g.get("text", "")) for g in groups if isinstance(g, dict))[:500],
            "body_summary_preview": " / ".join(body_lines[:6])[:500],
            "issues": ";".join(issues),
            "reviews": ";".join(reviews),
            "highlight_policy": HIGHLIGHT_POLICY,
        })

    payload = {
        "audit_version": AUDIT_VERSION,
        "count": len(rows),
        "issue_count": issue_count,
        "review_count": review_count,
        "highlight_policy": HIGHLIGHT_POLICY,
        "rows": rows,
    }
    for base in ["major_highlight_audit", "major_consistency_audit"]:
        (art / f"{base}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        fieldnames = [
            "game", "title", "source_url", "legacy_importance", "display_importance", "card_major", "derived_major",
            "major_group_count", "major_source_unit_total", "major_types", "major_group_text_preview",
            "body_summary_preview", "issues", "reviews", "highlight_policy",
        ]
        with (art / f"{base}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(f"[v040] major/highlight audit rows={len(rows)} issues={issue_count} reviews={review_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
