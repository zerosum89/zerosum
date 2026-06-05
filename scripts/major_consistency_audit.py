from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

AUDIT_VERSION = "github_actions_v041"
HIGHLIGHT_POLICY = (
    "major_group: body_summary update-units are classified as major only when they describe "
    "structural game changes. Multiple major units of the same type are grouped into one "
    "red summary sentence. Card major state is derived from major_group_count >= 1."
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


STRUCTURAL_ADD_ACTIONS = ["신규", "새로운", "추가", "도입", "신설", "오픈", "확장"]
STRUCTURAL_REWORK_ACTIONS = ["개편", "재편", "통합", "구조 변경", "구조가 변경", "구조가 개편", "규칙 변경", "방식 변경", "대규모"]
OPERATIONAL_MINOR_MARKERS = [
    "시즌", "이벤트", "출석", "미션", "교환소", "쿠폰", "지급", "회수", "삭제", "보상",
    "상자", "패키지", "상품", "패스", "소환권", "상점", "판매", "구매", "기간", "일정",
    "버그", "오류", "수정", "개선", "텍스트", "표시", "연출", "사운드", "확률", "수량",
    "랭킹", "매칭", "시드", "포인트", "정산", "밸런스", "수치", "효과 조정", "일부",
]


def _has_structural_action(text: str) -> bool:
    return has_any(text, STRUCTURAL_ADD_ACTIONS + STRUCTURAL_REWORK_ACTIONS)


def _has_operational_minor_marker(text: str) -> bool:
    return has_any(text, OPERATIONAL_MINOR_MARKERS)


def _contains_structural_phrase(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def _structural_added_or_reworked(text: str, nouns: list[str]) -> bool:
    return has_any(text, nouns) and _has_structural_action(text)


def _not_minor_unless_structural(text: str, structural_phrases: list[str]) -> bool:
    if _contains_structural_phrase(text, structural_phrases):
        return True
    return not _has_operational_minor_marker(text)


def major_type_for_line(line: str) -> str | None:
    """Return a major type only for structural game changes.

    v041 intentionally blocks domain-only detection.  A unit is major only when
    it adds/reworks a core content, PvP, growth, class, server/world, economy,
    or rule structure.  Operational updates, rewards, shop/BM, events, minor
    tuning, and bug fixes are excluded unless the same sentence explicitly
    describes a structural system/rule/axis change.
    """
    text = clean_line(line)
    d = domain(text)
    body = text.split(":", 1)[1].strip() if ":" in text else text
    combined = f"{d} {body}"

    # 1) PvP/war: require a new/reworked competitive structure, not season/reward/matching notices.
    pvp_structural_phrases = [
        "신규 전쟁", "신규 전장", "신규 점령", "신규 공성", "신규 PvP", "신규 경쟁 콘텐츠",
        "전쟁 콘텐츠가 추가", "전장 콘텐츠가 추가", "점령전 콘텐츠가 추가", "공성전 콘텐츠가 추가",
        "PvP 구조", "전쟁 구조", "점령 구조", "공성 구조", "경쟁 구조", "서버 단위 경쟁 구조",
    ]
    if _contains_structural_phrase(combined, pvp_structural_phrases):
        return "new_pvp_war"
    if _structural_added_or_reworked(combined, ["전쟁", "전장", "점령전", "공성전", "수성전", "쟁탈전", "월드 PvP", "경쟁 콘텐츠"]):
        if _not_minor_unless_structural(combined, ["구조", "규칙", "방식", "콘텐츠가 추가", "신규"]):
            return "new_pvp_war"

    # 2) Class/skill: require a new class/job/stance/skill system or large system rework.
    class_structural_phrases = [
        "신규 클래스", "클래스가 추가", "신규 전직", "전직이 추가", "신규 직업", "직업이 추가",
        "태세 시스템", "스킬 체계", "스킬 시스템", "클래스 구조", "전직 구조", "대규모 스킬 개편",
    ]
    if _contains_structural_phrase(combined, class_structural_phrases):
        return "class_skill_system"
    if _structural_added_or_reworked(combined, ["클래스", "직업", "전직", "태세", "스킬 체계", "스킬 시스템"]):
        if _not_minor_unless_structural(combined, ["신규", "시스템", "체계", "구조", "대규모"]):
            return "class_skill_system"

    # 3) Server/world: require world/server structure change, not ticket grant/recovery or schedule changes.
    server_structural_phrases = [
        "서버 통합", "월드군", "서버군", "신규 서버", "서버 구조", "월드 구조",
        "서버 이전 구조", "서버 이전 규칙", "서버 매칭 구조", "서버군 재편", "월드군 재편",
    ]
    if _contains_structural_phrase(combined, server_structural_phrases):
        if not _contains_structural_phrase(combined, ["이전권", "회수", "삭제", "지급", "보상", "기간 연장"]):
            return "server_world_structure"
    if _structural_added_or_reworked(combined, ["서버", "월드", "월드군", "서버군"]):
        if _not_minor_unless_structural(combined, ["통합", "재편", "신규 서버", "구조", "규칙"]):
            return "server_world_structure"

    # 4) Growth/equipment: require a new growth axis/system/part/stat, not rewards or item grants.
    growth_structural_phrases = [
        "신규 성장", "성장 시스템", "성장축", "신규 장비 부위", "신규 방어구 파츠", "신규 파츠",
        "신규 능력치", "신규 스테이터스", "스테이터스가 추가", "능력치가 추가", "각성 시스템",
        "강화 시스템", "유물 시스템", "아이템 수집", "도감 시스템", "전용 장비가 추가", "장비 구성이 추가",
    ]
    if _contains_structural_phrase(combined, growth_structural_phrases) and _has_structural_action(combined):
        if _not_minor_unless_structural(combined, ["시스템", "성장축", "부위", "파츠", "능력치", "스테이터스", "도감", "수집", "전용 장비"]):
            return "new_growth_axis"
    if _structural_added_or_reworked(combined, ["성장", "장비 부위", "방어구 파츠", "스테이터스", "능력치", "각성", "강화 시스템", "유물 시스템", "도감"]):
        if _not_minor_unless_structural(combined, ["시스템", "성장축", "신규", "추가", "개편"]):
            return "new_growth_axis"

    # 5) Economy/crafting: require economy/crafting/trading structure, not shop/product/reward updates.
    economy_structural_phrases = [
        "제작 구조", "거래 구조", "경제 구조", "재화 구조", "교환 구조", "거래소 구조",
        "제작 시스템", "거래 시스템", "재화 흐름", "소모 구조", "획득 구조",
    ]
    if _contains_structural_phrase(combined, economy_structural_phrases) and _has_structural_action(combined):
        return "economy_crafting_system"
    if _structural_added_or_reworked(combined, ["제작", "거래", "거래소", "재화", "경제"]):
        if _not_minor_unless_structural(combined, ["구조", "시스템", "흐름", "소모", "획득"]):
            return "economy_crafting_system"

    # 6) PvE content: require new/reworked playable content, not event reward/content schedule mentions.
    pve_structural_phrases = [
        "신규 챕터", "신규 지역", "신규 대륙", "신규 던전", "신규 레이드", "신규 보스", "신규 퀘스트",
        "챕터가 추가", "지역이 추가", "던전이 추가", "레이드가 추가", "보스가 추가", "퀘스트가 추가",
        "파티 던전", "월드 던전", "무한의 탑", "성채", "신규 콘텐츠",
    ]
    if _contains_structural_phrase(combined, pve_structural_phrases) and _has_structural_action(combined):
        if _not_minor_unless_structural(combined, ["신규", "추가", "개편", "콘텐츠", "던전", "레이드", "챕터", "지역"]):
            return "new_pve_content"
    if _structural_added_or_reworked(combined, ["챕터", "지역", "대륙", "던전", "레이드", "보스", "성채", "탑", "퀘스트", "콘텐츠"]):
        if _not_minor_unless_structural(combined, ["신규", "추가", "개편", "구조"]):
            return "new_pve_content"

    # 7) Major rule rework: require explicit structural rule/progression/reward rework.
    if _contains_structural_phrase(combined, ["진행 구조", "보상 구조", "참여 구조", "규칙 구조", "콘텐츠 구조", "핵심 규칙"]):
        if has_any(combined, ["개편", "변경", "조정", "재편"]):
            return "major_rule_rework"
    if has_any(combined, ["규칙", "방식", "구조"]) and has_any(combined, ["개편", "재편", "대규모 변경"]):
        if not _has_operational_minor_marker(combined):
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
    print(f"[v041] major/highlight audit rows={len(rows)} issues={issue_count} reviews={review_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
