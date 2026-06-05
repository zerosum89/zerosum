from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

AUDIT_VERSION = "github_actions_v047"
HIGHLIGHT_POLICY = (
    "major_group: body_summary update-units are classified as major only when they describe "
    "structural game changes; generic domain and 신규-word matches are blocked. Multiple major units of the same type are grouped into one "
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


# v043: compatibility for workflow script and audit script naming.
try:
    _has_any
except NameError:
    def _has_any(text: str, words: list[str]) -> bool:
        if "has_any" in globals():
            return has_any(text, words)
        return any(w in text for w in words)

STRUCTURAL_ADD_ACTIONS = ["신규", "새로운", "추가", "도입", "신설", "오픈", "확장"]
STRUCTURAL_REWORK_ACTIONS = ["개편", "재편", "통합", "구조 변경", "구조가 변경", "구조가 개편", "규칙 변경", "방식 변경", "대규모"]

# v043: these markers describe operational, reward, sales, season, cosmetic,
# bug-fix, minor tuning, or convenience updates. They do not make a unit major
# by themselves. They also suppress broad noun/action matching unless a
# stronger structural allow phrase is present.
OPERATIONAL_MINOR_MARKERS = [
    "시즌", "이벤트", "출석", "미션", "교환소", "쿠폰", "지급", "회수", "삭제", "보상",
    "상자", "패키지", "상품", "패스", "소환권", "상점", "판매", "구매", "기간", "일정",
    "버그", "오류", "수정", "개선", "텍스트", "표시", "연출", "사운드", "확률", "수량",
    "랭킹", "매칭", "시드", "포인트", "정산", "밸런스", "수치", "효과 조정", "일부",
    "외형", "형상", "코스튬", "스킨", "프리셋", "검색", "편의", "UI", "안내", "알림",
]

# Strong allow phrases describe structural additions/reworks. These are type
# level rules, not date/title-specific exceptions.
PVE_MAJOR_PHRASES = [
    "신규 챕터", "신규 지역", "신규 대륙", "신규 필드", "신규 월드", "신규 정규 던전",
    "신규 던전", "신규 파티 던전", "신규 월드 던전", "신규 레이드", "신규 보스",
    "신규 메인 퀘스트", "신규 서브 퀘스트", "챕터가 추가", "지역이 추가", "대륙이 추가",
    "필드가 추가", "던전이 추가", "레이드가 추가", "보스가 추가", "정규 콘텐츠가 추가",
]
PVP_MAJOR_PHRASES = [
    "신규 전쟁", "신규 전장", "신규 점령전", "신규 공성전", "신규 수성전", "신규 쟁탈전",
    "신규 월드 PvP", "신규 PvP 콘텐츠", "신규 경쟁 콘텐츠", "전쟁 콘텐츠가 추가",
    "전장 콘텐츠가 추가", "점령전 콘텐츠가 추가", "공성전 콘텐츠가 추가", "수성전 콘텐츠가 추가",
    "서버 단위 경쟁 구조", "전쟁 구조", "점령 구조", "공성 구조", "경쟁 구조",
]
CLASS_MAJOR_PHRASES = [
    "신규 클래스", "클래스가 추가", "신규 전직", "전직이 추가", "신규 직업", "직업이 추가",
    "신규 태세", "태세 시스템", "스킬 체계", "스킬 시스템", "클래스 구조", "전직 구조",
    "대규모 스킬 개편",
]
GROWTH_MAJOR_PHRASES = [
    "신규 성장 시스템", "성장 시스템", "성장축", "신규 성장축", "신규 장비 부위",
    "신규 방어구 파츠", "신규 장비 파츠", "신규 파츠", "신규 능력치", "신규 스테이터스",
    "스테이터스가 추가", "능력치가 추가", "각성 시스템", "강화 시스템", "유물 시스템",
    "신규 도감 시스템", "수집 시스템", "전용 장비가 추가", "장비 체계", "성장 단계가 확장",
]
SERVER_MAJOR_PHRASES = [
    "서버 통합", "월드군 재편", "서버군 재편", "신규 서버군", "신규 월드군",
    "서버 구조", "월드 구조", "서버 이전 구조", "서버 이전 규칙", "서버 매칭 구조",
]
ECONOMY_MAJOR_PHRASES = [
    "제작 구조", "거래 구조", "경제 구조", "재화 구조", "교환 구조", "거래소 구조",
    "제작 시스템", "거래 시스템", "재화 흐름", "소모 구조", "획득 구조",
]
RULE_MAJOR_PHRASES = [
    "진행 구조", "보상 구조", "참여 구조", "규칙 구조", "콘텐츠 구조", "핵심 규칙",
    "진행 방식이 개편", "보상 방식이 개편", "참여 방식이 개편", "규칙이 개편",
]


def _has_structural_action(text: str) -> bool:
    return _has_any(text, STRUCTURAL_ADD_ACTIONS + STRUCTURAL_REWORK_ACTIONS)


def _has_operational_minor_marker(text: str) -> bool:
    return _has_any(text, OPERATIONAL_MINOR_MARKERS)


def _contains_structural_phrase(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def _has_any_strong(text: str, phrase_groups: list[list[str]]) -> bool:
    return any(_contains_structural_phrase(text, group) for group in phrase_groups)


def _blocked_minor_context(text: str) -> bool:
    # True when the unit is operational/minor and lacks structural allow phrasing.
    if _has_any_strong(text, [PVE_MAJOR_PHRASES, PVP_MAJOR_PHRASES, CLASS_MAJOR_PHRASES, GROWTH_MAJOR_PHRASES, SERVER_MAJOR_PHRASES, ECONOMY_MAJOR_PHRASES, RULE_MAJOR_PHRASES]):
        return False
    return _has_operational_minor_marker(text)


def _structural_added_or_reworked(text: str, nouns: list[str]) -> bool:
    return _has_any(text, nouns) and _has_structural_action(text) and not _blocked_minor_context(text)

def _major_text(line: str) -> tuple[str, str, str]:
    text = clean_summary_line(line) if "clean_summary_line" in globals() else clean_line(line)
    d = summary_domain(text) if "summary_domain" in globals() else domain(text)
    body = text.split(":", 1)[1].strip() if ":" in text else text
    combined = f"{d} {body}"
    return text, d, combined


def _rx(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _has_all(text: str, markers: list[str]) -> bool:
    return all(m in text for m in markers)


def _non_structural_markers() -> list[str]:
    """Change-type exclusions. Generic rules only; no date/page hardcoding."""
    return [
        "신규 시즌", "새 시즌", "시즌 시작", "시즌이 시작", "시즌 갱신", "시즌이 갱신", "시즌 종료", "시즌 보상", "시즌",
        "이벤트", "출석", "미션", "교환소", "쿠폰", "상자", "패키지", "상품", "상점", "판매", "구매", "혜택", "출시 기념",
        "지급", "회수", "보전", "삭제", "기간", "일정", "확률", "수량", "랭킹", "매칭", "시드", "포인트", "정산",
        "버그", "오류", "수정", "개선", "텍스트", "표시", "연출", "사운드", "안내", "알림", "UI", "편의", "검색", "프리셋", "자동",
        "외형", "형상", "코스튬", "스킨", "의상", "아바타", "탈것", "보조 장비", "무기 외형", "무기 형상",
        "수집 목록", "아이템 수집", "수집 25종", "잠금 기능", "획득처 정보", "기술 정보창",
        "신규 지속 기술", "공통 신규 지속 기술", "클래스 변경", "Class Change", "클래스 변경권", "직업 변경",
        "일부", "소폭", "밸런스", "수치", "효과 조정", "난이도", "단계", "층", "보스 교체",
        "툴팁", "문구", "버튼", "아이콘", "색상", "품목", "구성", "구성 개선", "구성 갱신",
    ]


def _has_non_structural_context(text: str, extra: list[str] | None = None) -> bool:
    return _has_any(text, _non_structural_markers() + list(extra or []))


def _is_ambiguous_or_template_major_text(text: str) -> bool:
    """Reject vague/template-like summary sentences as Major evidence."""
    generic_markers = [
        "신규 및 변경 사항", "관련 이용 목표", "관련 이용", "신규/변경", "주요 변경", "다양한",
        "관련 콘텐츠", "공략 구간", "플레이 목표", "관련 콘텐츠가 추가", "관련 콘텐츠가 추가·개편",
        "신규 필드·지역 또는 전용 사냥 구역", "월드 던전이 추가되거나 시즌이 갱신",
        "추가되거나", "또는", "보상 구조가 갱신", "보상 구조가 조정", "보상 구조가 확장",
        "보상 구성이 갱신", "보상 구성이 조정", "구성이 갱신", "구성이 개선",
        "이용 흐름과 정보 확인 방식", "성장 재료 획득 루트가 조정", "신규/변경 사항",
    ]
    return _has_any(text, generic_markers)


def _is_reward_or_material_explanation(text: str) -> bool:
    """Reward/drop/material sentences are not Major evidence by themselves."""
    reward_markers = [
        "처치하면", "획득", "드랍", "드롭", "재료", "보상", "입장 비용", "구매 횟수", "교환", "상점",
        "제작의 키 재료", "제작 재료", "획득 루트", "획득처", "아이템을 획득", "보상으로",
    ]
    return _has_any(text, reward_markers)


def _is_ui_or_mission_flow(text: str) -> bool:
    ui_markers = ["임무 페이지", "의뢰 페이지", "페이지", "노출", "자동 이동", "자동이동", "화면", "탭", "필터", "정렬", "표시"]
    return _has_any(text, ui_markers)


def _has_concrete_target(text: str) -> bool:
    """Require an identifiable target name, quoted term, numbered chapter, or proper noun-like token."""
    if re.search(r"[‘'\"][^‘’'\"]{2,40}[’'\"]", text):
        return True
    if re.search(r"\b\d+\s*(?:챕터|장|막|차|번째|th|st|nd|rd)\b", text, flags=re.IGNORECASE):
        return True
    english_targets = re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,4}\b", text)
    generic = {"PvE", "PvP", "UI", "BM", "NPC", "PC", "KR", "Global", "Class", "Change"}
    if any(t not in generic and len(t) >= 4 for t in english_targets):
        return True
    if re.search(r"[가-힣A-Za-z0-9·]{2,24}\s*(?:챕터|지역|대륙|필드|던전|레이드|보스|클래스|직업|전직|태세|성장 시스템|성장축|장비 부위|방어구 파츠|스탯 축|스테이터스|서버군|월드군)", text):
        if not re.search(r"(?:신규|새로운|정규|월드|파티|필드·지역|전용 사냥 구역)\s*(?:챕터|지역|대륙|필드|던전|레이드|보스|콘텐츠)", text):
            return True
    return False


def _major_evidence_ok(text: str, *, require_target: bool = True) -> bool:
    if _is_ambiguous_or_template_major_text(text):
        return False
    if _is_reward_or_material_explanation(text):
        return False
    if _is_ui_or_mission_flow(text):
        return False
    if require_target and not _has_concrete_target(text):
        return False
    return True


def _is_specific_pve_structural_add(text: str) -> bool:
    """v047: PvE Major requires target + content type + structural add/open action."""
    if not _major_evidence_ok(text):
        return False
    if _has_non_structural_context(text, [
        "시즌", "보스 교체", "난이도", "단계", "층", "이벤트", "임무", "의뢰", "페이지", "자동 이동", "노출",
        "몬스터", "정예 몬스터", "일반 몬스터", "재료", "보상", "드랍", "처치하면",
    ]):
        # Keep explicit named boss/raid exceptions below; generic monster/reward/flow sentences stay excluded.
        if not _rx(text, r"(신규|새로운).{0,18}(레이드|필드 보스|월드 보스|보스 콘텐츠)"):
            return False
    action = r"(추가|도입|신설|오픈|개방|공개|열립니다|추가됩니다|오픈됩니다|개방됩니다)"
    # Chapter/region/world field additions.
    if _rx(text, rf"(신규|새로운).{{0,18}}([A-Za-z가-힣0-9·'‘’\" ]{{2,40}})?(챕터|지역|대륙|필드){{1}}.{{0,18}}{action}"):
        return True
    if _rx(text, rf"(챕터|지역|대륙|필드).{{0,18}}{action}") and _rx(text, r"(신규|새로운|새 |오픈|개방)"):
        return True
    # Regular dungeon/raid/boss content additions. Do not accept season refreshes or difficulty/stage additions.
    if _rx(text, rf"(신규|새로운).{{0,22}}(정규 던전|파티 던전|월드 던전|던전|레이드|필드 보스|월드 보스|보스 콘텐츠).{{0,22}}{action}"):
        return True
    if _rx(text, rf"(정규 던전|파티 던전|월드 던전|던전|레이드|필드 보스|월드 보스|보스 콘텐츠).{{0,22}}{action}") and _rx(text, r"(신규|새로운|새 |오픈|개방)"):
        return True
    # Main/sub quests only count when tied to a concrete new chapter/region, not as ordinary mission UI/flow.
    if _rx(text, rf"(메인 퀘스트|서브 퀘스트).{{0,18}}{action}") and _has_any(text, ["챕터", "지역", "대륙"]):
        return True
    return False


def major_type_for_line(line: str) -> str | None:
    """Return Major type for structural update-units only.

    v047 keeps Major as a strict boolean derived judgement.
    Source of truth is the body_summary/update-unit sentence only.
    PvE Major is further tightened: it requires concrete target + content type + add/open action.
    Reward/material explanations, mission/page/auto-move UI flow, generic related-content templates,
    season/stage/difficulty additions, cosmetic/function adjustments, and mixed 'or/added or season renewed'
    sentences are rejected by rule rather than by patch-specific hardcoding.
    """
    _text, d, combined = _major_text(line)
    text = combined
    if _is_ambiguous_or_template_major_text(text):
        return None

    if _is_specific_pve_structural_add(text):
        return "new_pve_content"

    if not _has_non_structural_context(text, ["시즌", "매칭", "랭킹", "포인트", "보상"]) and _major_evidence_ok(text):
        if _rx(text, r"(신규|새로운).{0,20}(전쟁 콘텐츠|전장 콘텐츠|점령전|공성전|수성전|쟁탈전|월드 PvP|PvP 콘텐츠|경쟁 콘텐츠|월드 격전지|격전지)"):
            return "new_pvp_war"
        if _rx(text, r"(전쟁 콘텐츠|전장 콘텐츠|점령전|공성전|수성전|쟁탈전|월드 PvP|PvP 콘텐츠|경쟁 콘텐츠|월드 격전지|격전지).{0,20}(추가|도입|신설|오픈|개방)"):
            return "new_pvp_war"
        if _rx(text, r"(전쟁|점령|공성|수성|쟁탈|경쟁).{0,12}(구조|규칙|방식).{0,20}(전면 개편|대규모 개편|개편|재편|변경)"):
            return "new_pvp_war"

    if not _has_non_structural_context(text, ["전설 보조 장비", "지속 기술", "기술 추가", "스킬 추가", "Class Change", "클래스 변경", "변경권"]):
        if _major_evidence_ok(text) and _rx(text, r"(신규|새로운).{0,16}(클래스|직업|전직)"):
            return "class_skill_system"
        if _major_evidence_ok(text) and _rx(text, r"(클래스|직업|전직).{0,8}(추가|도입|신설)") and not _rx(text, r"(클래스별|전 클래스|클래스 공통|변경|변경권)"):
            return "class_skill_system"
        if _rx(text, r"(스킬 체계|스킬 시스템|클래스 구조|전직 구조|태세 시스템).{0,20}(추가|도입|전면 개편|대규모 개편|개편|재편)") and _major_evidence_ok(text, require_target=False):
            return "class_skill_system"
        if _major_evidence_ok(text) and _rx(text, r"(신규|새로운).{0,16}태세") and not _has_any(text, ["능력치 조정", "표시", "전환 상태", "조정"]):
            return "class_skill_system"

    growth_exclude = ["수집", "획득처", "잠금", "유지할 수 있는 기능", "정보가 추가", "외형", "형상", "보상", "상품", "패키지", "계열 성장 시스템", "재료"]
    if not _has_non_structural_context(text, growth_exclude) and not _is_reward_or_material_explanation(text):
        if _major_evidence_ok(text) and _rx(text, r"(신규|새로운).{0,20}(성장 시스템|성장축|장비 부위|방어구 파츠|장비 파츠|스탯 축|스테이터스|각성 시스템|강화 시스템|계승 시스템|장비 체계)"):
            return "new_growth_axis"
        if _major_evidence_ok(text) and _rx(text, r"(성장 시스템|성장축|장비 부위|방어구 파츠|장비 파츠|스탯 축|스테이터스|각성 시스템|강화 시스템|계승 시스템|장비 체계).{0,20}(추가|도입|신설|확장|개편)"):
            return "new_growth_axis"
        if _major_evidence_ok(text) and _has_any(text, ["성장 단계가 확장", "장기 성장축이 확장", "장비 축복 시스템이 추가", "수호정령이 새롭게 추가"]):
            return "new_growth_axis"

    if not _has_non_structural_context(text, ["이전권", "회수", "지급", "보상"]):
        if _has_any(text, ["서버 통합", "월드군 재편", "서버군 재편", "신규 서버군", "신규 월드군"]):
            return "server_world_structure"
        if _rx(text, r"(서버 구조|월드 구조|서버 이전 구조|서버 매칭 구조).{0,20}(개편|재편|변경|통합)"):
            return "server_world_structure"

    if not _has_non_structural_context(text, ["품목", "구성", "교환 아이템", "보상"]):
        if _rx(text, r"(제작 구조|거래 구조|경제 구조|재화 구조|교환 구조|거래소 구조|제작 시스템|거래 시스템|재화 흐름|소모 구조|획득 구조).{0,22}(추가|도입|개편|재편|변경)"):
            return "economy_crafting_system"

    if not _has_non_structural_context(text, ["보상 구성이", "보상 갱신"]):
        if _rx(text, r"(진행 구조|참여 구조|규칙 구조|콘텐츠 구조|핵심 규칙).{0,22}(전면 개편|대규모 개편|개편|재편|변경)"):
            return "major_rule_rework"
        if _rx(text, r"보상 구조.{0,12}(전면 개편|대규모 개편|개편|재편)"):
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

def _xlsx_cell(v: Any) -> str:
    import html
    s = "" if v is None else str(v)
    s = s.replace("\r", " ").replace("\n", " ")
    return f'<c t="inlineStr"><is><t>{html.escape(s)}</t></is></c>'


def _xlsx_sheet(rows: list[list[Any]]) -> bytes:
    body = []
    for r_idx, row in enumerate(rows, 1):
        cells = "".join(_xlsx_cell(v) for v in row)
        body.append(f'<row r="{r_idx}">{cells}</row>')
    xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(body) + '</sheetData></worksheet>'
    return xml.encode("utf-8")


def write_major_quality_audit_xlsx(path: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    import zipfile
    from collections import Counter
    fields = ["game", "title", "source_url", "legacy_importance", "display_importance", "card_major", "derived_major", "major_group_count", "major_source_unit_total", "major_types", "major_group_text_preview", "body_summary_preview", "issues", "reviews", "highlight_policy"]
    type_counter = Counter()
    game_counter = Counter()
    month_counter = Counter()
    fp_candidates = []
    for r in rows:
        game_counter[str(r.get("game", ""))] += 1
        title = str(r.get("title", ""))
        month_counter[title[:5] if len(title) >= 5 else title] += 1
        for t in str(r.get("major_types", "")).split(" / "):
            if t.strip():
                type_counter[t.strip()] += 1
        if any(x in str(r.get("body_summary_preview", "")) for x in ["시즌", "이벤트", "상품", "외형", "형상", "보상", "편의", "검색", "프리셋"]):
            fp_candidates.append(r)
    sheets = [
        ("Summary", [["key", "value"], ["audit_version", payload.get("audit_version")], ["rows", payload.get("count")], ["issue_count", payload.get("issue_count")], ["review_count", payload.get("review_count")], ["highlight_policy", payload.get("highlight_policy")]]),
        ("Major Type Count", [["major_type", "count"]] + [[k, v] for k, v in type_counter.most_common()]),
        ("Major By Game", [["game", "count"]] + [[k, v] for k, v in game_counter.most_common()]),
        ("Major By Month", [["month", "count"]] + [[k, v] for k, v in month_counter.most_common()]),
        ("False Positive Candidates", [fields] + [[r.get(f, "") for f in fields] for r in fp_candidates[:120]]),
        ("Sample Major 60", [fields] + [[r.get(f, "") for f in fields] for r in rows if str(r.get("display_importance", "")).lower() == "major"][:60]),
        ("Sample Normal 40", [fields] + [[r.get(f, "") for f in fields] for r in rows if str(r.get("display_importance", "")).lower() != "major"][:40]),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1)) + '</Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{name[:31]}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1)) + '</sheets></workbook>')
        for i, (_, sheet_rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _xlsx_sheet(sheet_rows))

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
        if derived_major and any(x in " / ".join(body_lines) for x in ["시즌", "이벤트", "상품", "외형", "편의", "쿠폰", "보상"]):
            reviews.append("check_structural_major_context")
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
    write_major_quality_audit_xlsx(art / "major_quality_audit.xlsx", payload, rows)
    print(f"[v047] major/highlight audit rows={len(rows)} issues={issue_count} reviews={review_count} xlsx=major_quality_audit.xlsx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
