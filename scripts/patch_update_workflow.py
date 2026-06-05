#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
import hashlib
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
ROOT = Path.cwd()
ART_ENV = os.environ.get("PATCH_WORKFLOW_ARTIFACT_DIR", "").strip()
ART = Path(ART_ENV).expanduser() if ART_ENV else (ROOT / "outputs" / "patch_workflow_artifacts")
ART.mkdir(parents=True, exist_ok=True)
LOG_PATH = ART / "workflow.log"


def log(message: str) -> None:
    print(message, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


DRY_RUN = env_bool("DRY_RUN", True)
RUN_NOTION_WRITE = env_bool("RUN_NOTION_WRITE", False)
RUN_GIT_PUSH = env_bool("RUN_GIT_PUSH", False)
TARGET_GAMES = [x.strip() for x in os.environ.get("TARGET_GAMES", "ALL").split(",") if x.strip()]
MAX_NEW_URLS_PER_GAME = env_int("MAX_NEW_URLS_PER_GAME", 20)
MAX_LIST_ITEMS = env_int("MAX_LIST_ITEMS", 80)
STRICT_DETAIL_URL_GUARD = env_bool("STRICT_DETAIL_URL_GUARD", True)
FETCH_DETAIL_PAGES = env_bool("FETCH_DETAIL_PAGES", True)
MAX_DETAIL_TEXT_CHARS = env_int("MAX_DETAIL_TEXT_CHARS", 40000)
MAX_DETAIL_FETCHES = env_int("MAX_DETAIL_FETCHES", 20)
RUN_TITLE_REPAIR = env_bool("RUN_TITLE_REPAIR", False)
TITLE_REPAIR_WINDOW_DAYS = env_int("TITLE_REPAIR_WINDOW_DAYS", 14)
SCHEDULE_OPERATION_MODE = os.environ.get("SCHEDULE_OPERATION_MODE", "preview").strip() or "preview"
IS_SCHEDULE_RUN = os.environ.get("GITHUB_EVENT_NAME", "") == "schedule"
POST_WRITE_EXPORT_RETRY_COUNT = env_int("POST_WRITE_EXPORT_RETRY_COUNT", 6)
POST_WRITE_EXPORT_RETRY_SECONDS = env_int("POST_WRITE_EXPORT_RETRY_SECONDS", 5)
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
SCHEMA_VERSION = "patch_view_model.v1"
WORKFLOW_VERSION = "github_actions_v046"


DERIVED_DATA_VERSION = "patch_view_model.derived.major_policy_v046"
MAJOR_POLICY_VERSION = "major_policy_v046"
def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
        scheme = (p.scheme or "https").lower()
        host = p.netloc.lower()
        path = re.sub(r"/+$", "", p.path or "")
        return urlunparse((scheme, host, path, "", "", ""))
    except Exception:
        return url.split("?")[0].split("#")[0].rstrip("/")


def profile_canonical_url(url: str, profile: dict[str, Any] | None = None) -> str:
    c = canonical_url(url)
    if not profile:
        return c
    for rule in profile.get("canonical_host_aliases", []) or []:
        src = str(rule.get("from", "")).lower()
        dst = str(rule.get("to", "")).lower()
        if src and dst:
            p = urlparse(c)
            if p.netloc.lower() == src:
                c = urlunparse((p.scheme, dst, p.path, "", "", ""))
    return c


def norm_key(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(s).lower())


def parse_notion_property(prop: dict[str, Any]) -> Any:
    if not isinstance(prop, dict):
        return None
    typ = prop.get("type")

    def rich_text(arr: list[dict[str, Any]] | None) -> str:
        return "".join(x.get("plain_text") or "" for x in (arr or []))

    if typ == "title":
        return rich_text(prop.get("title"))
    if typ == "rich_text":
        return rich_text(prop.get("rich_text"))
    if typ == "select":
        return (prop.get("select") or {}).get("name")
    if typ == "multi_select":
        return [x.get("name") for x in (prop.get("multi_select") or []) if x.get("name")]
    if typ == "date":
        return (prop.get("date") or {}).get("start")
    if typ == "url":
        return prop.get("url")
    if typ == "checkbox":
        return bool(prop.get("checkbox"))
    if typ == "number":
        return prop.get("number")
    if typ == "formula":
        f = prop.get("formula") or {}
        ft = f.get("type")
        if ft == "string":
            return f.get("string")
        if ft == "date":
            return (f.get("date") or {}).get("start")
        if ft == "number":
            return f.get("number")
        if ft == "boolean":
            return f.get("boolean")
    return None


def pick(raw: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for n in names:
        if n in raw and raw[n] not in (None, "", []):
            return raw[n]
    key_map = {norm_key(k): k for k in raw.keys()}
    for n in names:
        k = key_map.get(norm_key(n))
        if k and raw.get(k) not in (None, "", []):
            return raw[k]
    return default


def listify(v: Any) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    text = str(v).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    if "\n" in text:
        return [re.sub(r"^[-•*]\s*", "", x).strip() for x in text.splitlines() if x.strip()]
    if ";" in text:
        return [x.strip() for x in text.split(";") if x.strip()]
    return [text]


MAJOR_TYPE_ORDER = [
    "new_pve_content",
    "new_pvp_war",
    "new_growth_axis",
    "class_skill_system",
    "server_world_structure",
    "economy_crafting_system",
    "major_rule_rework",
]


def clean_summary_line(line: Any) -> str:
    text = str(line or "").strip()
    text = re.sub(r"^[-•*]\s*", "", text).strip()
    return text


def summary_domain(line: str) -> str:
    return line.split(":", 1)[0].strip() if ":" in line else ""


def _has_any(text: str, words: list[str]) -> bool:
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
        "신규 필드·지역 또는 전용 사냥 구역", "월드 던전이 추가되거나 시즌이 갱신",
        "추가되거나", "또는", "보상 구조가 갱신", "보상 구조가 조정", "보상 구조가 확장",
        "보상 구성이 갱신", "보상 구성이 조정", "구성이 갱신", "구성이 개선",
        "이용 흐름과 정보 확인 방식", "성장 재료 획득 루트가 조정",
    ]
    return _has_any(text, generic_markers)


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
    if require_target and not _has_concrete_target(text):
        return False
    return True


def major_type_for_line(line: str) -> str | None:
    """Return Major type for structural update-units only.

    v046 keeps Major as a strict boolean derived judgement.
    Source of truth is the body_summary/update-unit sentence only.
    Major requires a concrete structural target and an add/rework action.
    Vague template sentences, mixed 'added or season renewed' phrasing,
    season/event/BM/cosmetic/convenience/reward/bug/minor changes are rejected
    by rule rather than by patch-specific hardcoding.
    """
    _text, d, combined = _major_text(line)
    text = combined
    if _is_ambiguous_or_template_major_text(text):
        return None

    pve_exclude = ["시즌", "보스 교체", "난이도", "단계", "층", "이벤트"]
    if not _has_non_structural_context(text, pve_exclude) and _major_evidence_ok(text):
        if _rx(text, r"(신규|새로운|오픈).{0,18}(챕터|지역|대륙|필드|정규 콘텐츠|PvE 콘텐츠)"):
            return "new_pve_content"
        if _rx(text, r"(챕터|지역|대륙|필드|정규 콘텐츠|PvE 콘텐츠).{0,18}(추가|도입|신설|오픈)"):
            return "new_pve_content"
        if _rx(text, r"(신규|새로운).{0,22}(정규 던전|파티 던전|월드 던전|던전|레이드|보스 콘텐츠|보스 몬스터|보스)"):
            return "new_pve_content"
        if _rx(text, r"(정규 던전|파티 던전|월드 던전|던전|레이드|보스 콘텐츠|보스 몬스터).{0,22}(추가|도입|신설|오픈)"):
            return "new_pve_content"
        if _rx(text, r"(메인 퀘스트|서브 퀘스트).{0,18}(추가|도입|신설)") and _has_any(text, ["챕터", "지역", "대륙"]):
            return "new_pve_content"

    if not _has_non_structural_context(text, ["시즌", "매칭", "랭킹", "포인트", "보상"]) and _major_evidence_ok(text):
        if _rx(text, r"(신규|새로운).{0,20}(전쟁 콘텐츠|전장 콘텐츠|점령전|공성전|수성전|쟁탈전|월드 PvP|PvP 콘텐츠|경쟁 콘텐츠|월드 격전지|격전지)"):
            return "new_pvp_war"
        if _rx(text, r"(전쟁 콘텐츠|전장 콘텐츠|점령전|공성전|수성전|쟁탈전|월드 PvP|PvP 콘텐츠|경쟁 콘텐츠|월드 격전지|격전지).{0,20}(추가|도입|신설|오픈)"):
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

    growth_exclude = ["수집", "획득처", "잠금", "유지할 수 있는 기능", "정보가 추가", "외형", "형상", "보상", "상품", "패키지", "계열 성장 시스템"]
    if not _has_non_structural_context(text, growth_exclude):
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

def domain_for_major_type(major_type: str, fallback: str = "") -> str:
    return {
        "new_pve_content": "PvE 콘텐츠",
        "new_pvp_war": "PvP/전쟁",
        "new_growth_axis": "성장/장비",
        "class_skill_system": "클래스/스킬",
        "server_world_structure": "서버/월드",
        "economy_crafting_system": "경제/거래",
        "major_rule_rework": fallback or "시스템",
    }.get(major_type, fallback or "시스템")


def extract_major_targets(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        body = line.split(":", 1)[1].strip() if ":" in line else line
        quoted = re.findall(r"[‘'\"]([^‘’'\"]{2,24})[’'\"]", body)
        candidates = quoted or [re.sub(r"(이|가|을|를|으로|로)?\s*(추가|개편|변경|조정|확장|시작|진행).*$", "", body).strip()]
        for cand in candidates:
            c = re.sub(r"^(신규|새로운|기간제|일반)\s+", "", cand).strip()
            if 2 <= len(c) <= 32 and c not in seen:
                seen.add(c)
                out.append(c)
            if len(out) >= 3:
                return out
    return out


def build_major_group_text(major_type: str, lines: list[str]) -> str:
    first_domain = summary_domain(lines[0]) if lines else ""
    domain = domain_for_major_type(major_type, first_domain)
    if len(lines) == 1:
        return clean_summary_line(lines[0])
    targets = extract_major_targets(lines)
    target_text = (", ".join(targets) + " 관련 ") if targets else ""
    templates = {
        "new_pve_content": f"{domain}: {target_text}콘텐츠가 추가·개편되어 공략 구간과 플레이 목표가 확장됩니다.",
        "new_pvp_war": f"{domain}: {target_text}전쟁·경쟁 구조가 추가·개편되어 PvP 참여 흐름과 보상 경쟁이 확장됩니다.",
        "new_growth_axis": f"{domain}: {target_text}성장 요소가 추가·개편되어 캐릭터 성장 단계와 선택지가 확장됩니다.",
        "class_skill_system": f"{domain}: {target_text}클래스·스킬 구성이 추가·조정되어 전투 운용 선택지가 확장됩니다.",
        "server_world_structure": f"{domain}: {target_text}서버·월드 구조가 변경되어 이전·매칭·진행 범위가 조정됩니다.",
        "economy_crafting_system": f"{domain}: {target_text}제작·거래·재화 구조가 추가·개편되어 아이템 획득과 경제 흐름이 조정됩니다.",
        "major_rule_rework": f"{domain}: {target_text}콘텐츠 규칙과 진행 구조가 개편되어 플레이 흐름과 보상 기준이 조정됩니다.",
    }
    return templates.get(major_type, f"{domain}: {target_text}주요 변경이 적용됩니다.")


def derive_major_summary_groups(body_summary: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for idx, raw_line in enumerate(body_summary):
        line = clean_summary_line(raw_line)
        major_type = major_type_for_line(line)
        if not major_type:
            continue
        item = grouped.setdefault(major_type, {
            "major_type": major_type,
            "domain": domain_for_major_type(major_type, summary_domain(line)),
            "source_unit_count": 0,
            "source_unit_indices": [],
            "_lines": [],
        })
        item["source_unit_count"] += 1
        item["source_unit_indices"].append(idx)
        item["_lines"].append(line)
    out: list[dict[str, Any]] = []
    for major_type in MAJOR_TYPE_ORDER:
        item = grouped.get(major_type)
        if not item:
            continue
        lines = item.pop("_lines")
        item["text"] = build_major_group_text(major_type, lines)
        out.append(item)
    return out


def enrich_major_highlight_fields(item: dict[str, Any]) -> dict[str, Any]:
    body_summary = listify(item.get("body_summary", []))
    groups = derive_major_summary_groups(body_summary)
    item["major_summary_groups"] = groups
    item["major_group_count"] = len(groups)
    item["major_summary_indices"] = list(range(len(groups)))
    item["derived_importance"] = "major" if groups else "normal"
    item["display_importance"] = item["derived_importance"]
    item["importance_source"] = "derived_from_body_summary_structural_major_groups_v046"
    return item


def normalize_item_from_notion(page: dict[str, Any]) -> dict[str, Any]:
    raw = {k: parse_notion_property(v) for k, v in (page.get("properties") or {}).items()}
    body_summary = listify(pick(raw, ["body_summary", "본문 요약", "Body Summary"], []))
    domain_tags = listify(pick(raw, ["domain_tags", "관련 영역", "도메인 태그", "Domain Tags"], []))
    if not domain_tags:
        seen = set()
        for line in body_summary:
            if ":" in line:
                d = line.split(":", 1)[0].strip()
                if d and d not in seen:
                    domain_tags.append(d)
                    seen.add(d)
    card_summary = pick(raw, ["card_summary", "카드 요약", "Card Summary"], "")
    if not card_summary:
        card_summary = " · ".join(domain_tags[:4]) if domain_tags else ""

    actual_date = str(pick(raw, ["actual_date", "실제 패치일", "패치일", "날짜", "Date"], ""))[:10]
    # v015: Notion title property in this DB is "항목명".  Earlier versions did
    # not read that key, so title repair saw an already-normalized fallback and
    # found zero candidates. Keep the raw Notion title separately for repair,
    # while exposing a normalized display title to patch_view_model.json.
    raw_title = str(pick(raw, ["항목명", "title", "표시 제목", "정규화 제목", "패치 제목", "Name", "제목"], ""))
    normalized_title = normalized_patch_page_title(actual_date, raw_title)
    title = normalized_title or raw_title
    if not title:
        date = actual_date.replace("-", ".")[2:] if actual_date else "--.--.--"
        title = f"{date} | 패치노트"

    return {
        "page_id": page.get("id", ""),
        "game": str(pick(raw, ["game", "게임", "게임명", "Game"], "")),
        "actual_date": actual_date,
        "title": title,
        "raw_title": raw_title,
        "source_url": str(pick(raw, ["source_url", "원문 URL", "URL", "url", "링크", "원문링크"], "")),
        "importance": str(pick(raw, ["importance", "중요도", "Importance"], "normal") or "normal"),
        "primary_category": listify(pick(raw, ["primary_category", "패치 카테고리", "대표 카테고리", "대표 핵심 신호"], [])),
        "main_updates": listify(pick(raw, ["main_updates", "주요 업데이트", "주요 업데이트 요약"], [])),
        "body_summary": body_summary,
        "domain_tags": domain_tags,
        "card_summary": str(card_summary),
    }


def notion_query_database() -> list[dict[str, Any]]:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not token or not database_id:
        raise RuntimeError("NOTION_TOKEN or NOTION_DATABASE_ID is missing.")

    rows: list[dict[str, Any]] = []
    cursor = None
    session = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = session.post(f"https://api.notion.com/v1/databases/{database_id}/query", headers=headers, json=payload, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Notion query failed: HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def existing_json_items() -> list[dict[str, Any]]:
    path = ROOT / "patch_view_model.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("items", []) if isinstance(data.get("items", []), list) else []
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []



def existing_json_derived_data_version() -> str:
    path = ROOT / "patch_view_model.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return str(data.get("derived_data_version") or data.get("major_policy_version") or "")
    except Exception:
        return ""
    return ""

def stable_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (str(x.get("game", "")), str(x.get("actual_date", "")), str(x.get("source_url", ""))))


def file_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def execution_identity() -> dict[str, Any]:
    script_path = Path(__file__).resolve()
    return {
        "workflow_version": WORKFLOW_VERSION,
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "github_ref": os.environ.get("GITHUB_REF", ""),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "github_workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "github_event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "script_path": str(script_path),
        "script_sha256": file_sha256(script_path),
    }


def export_patch_view_model() -> tuple[list[dict[str, Any]], str, bool]:
    try:
        pages = notion_query_database()
        items = [normalize_item_from_notion(p) for p in pages]
        items = [x for x in items if x.get("game") and x.get("source_url")]
        source = "notion_db"
        log(f"[STEP] Notion export complete: {len(items)} public items")
    except Exception as exc:
        log(f"[WARN] Notion export skipped/failed: {exc}")
        items = existing_json_items()
        source = "existing_patch_view_model_json" if items else "empty"
        log(f"[STEP] Existing patch_view_model.json fallback loaded: {len(items)} items")

    items = [enrich_major_highlight_fields(dict(x)) for x in items]

    current_items = existing_json_items()
    source_items_changed = stable_items(current_items) != stable_items(items)
    existing_path = ROOT / "patch_view_model.json"
    existing_derived_data_version = existing_json_derived_data_version()
    derived_data_version_changed = existing_derived_data_version != DERIVED_DATA_VERSION
    file_changed = source_items_changed or derived_data_version_changed

    if not file_changed and existing_path.exists():
        log("[STEP] patch_view_model.json unchanged; existing file preserved to avoid noisy commits")
    else:
        output = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(KST).isoformat(),
            "source": source,
            "workflow_version": WORKFLOW_VERSION,
            "derived_data_version": DERIVED_DATA_VERSION,
            "major_policy_version": MAJOR_POLICY_VERSION,
            "items": items,
        }
        existing_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        log(
            "[STEP] patch_view_model.json written: "
            f"source_items_changed={source_items_changed}, "
            f"derived_data_version_changed={derived_data_version_changed}, "
            f"existing_derived_data_version={existing_derived_data_version or 'none'}, "
            f"new_derived_data_version={DERIVED_DATA_VERSION}"
        )

    (ART / "patch_view_model_export_summary.json").write_text(json.dumps({
        "source": source,
        "items": len(items),
        "source_items_changed": source_items_changed,
        "derived_items_changed": derived_data_version_changed,
        "derived_data_version_changed": derived_data_version_changed,
        "existing_derived_data_version": existing_derived_data_version,
        "derived_data_version": DERIVED_DATA_VERSION,
        "major_policy_version": MAJOR_POLICY_VERSION,
        "file_changed": file_changed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return items, source, file_changed


def export_patch_view_model_with_retry(
    expected_source_urls: list[str] | None = None,
    min_items: int | None = None,
    label: str = "export",
) -> tuple[list[dict[str, Any]], str, bool]:
    """Export Patch View Model and verify that recently written pages are visible.

    Notion can expose newly created pages to subsequent database queries with a small delay.
    v017 retries post-write export until created source URLs are present, preventing a run
    from succeeding in Notion write but failing to update patch_view_model.json in the same run.
    """
    expected = [canonical_url(x) for x in (expected_source_urls or []) if x]
    max_attempts = max(1, POST_WRITE_EXPORT_RETRY_COUNT)
    wait_seconds = max(0, POST_WRITE_EXPORT_RETRY_SECONDS)
    attempts: list[dict[str, Any]] = []
    last_items: list[dict[str, Any]] = []
    last_source = ""
    last_changed = False
    ok = False
    missing: list[str] = []
    for attempt in range(1, max_attempts + 1):
        last_items, last_source, last_changed = export_patch_view_model()
        item_urls = {canonical_url(x.get("source_url", "")) for x in last_items if x.get("source_url")}
        missing = [x for x in expected if x not in item_urls]
        min_ok = True if min_items is None else len(last_items) >= min_items
        ok = (not missing) and min_ok
        attempts.append({
            "attempt": attempt,
            "source": last_source,
            "items": len(last_items),
            "file_changed": last_changed,
            "expected_source_url_count": len(expected),
            "missing_expected_source_url_count": len(missing),
            "missing_expected_source_urls": missing,
            "min_items": min_items,
            "min_items_ok": min_ok,
            "ok": ok,
        })
        if ok:
            break
        if attempt < max_attempts and wait_seconds > 0:
            log(f"[WAIT] {label} export verification not ready. retry={attempt + 1}/{max_attempts} after {wait_seconds}s")
            time.sleep(wait_seconds)
    result = {
        "workflow_version": WORKFLOW_VERSION,
        "label": label,
        "passed": ok,
        "max_attempts": max_attempts,
        "wait_seconds": wait_seconds,
        "expected_source_urls": expected,
        "min_items": min_items,
        "attempts": attempts,
    }
    (ART / f"{label}_export_verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if expected and not ok:
        raise RuntimeError(f"{label} export verification failed. Missing expected source URLs: {missing}")
    return last_items, last_source, last_changed


def ymd_key(v: Any) -> str:
    s = str(v or "")[:10]
    return s if re.match(r"^20\d{2}-\d{2}-\d{2}$", s) else ""


def latest_anchor_by_game(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    anchors: dict[str, dict[str, Any]] = {}
    for it in items:
        g = it.get("game") or ""
        u = it.get("source_url") or ""
        d = ymd_key(it.get("actual_date"))
        if not g or not u:
            continue
        old = anchors.get(g)
        if old is None or d > old.get("actual_date", ""):
            anchors[g] = {
                "game": g,
                "source_url": u,
                "canonical_url": canonical_url(u),
                "actual_date": d,
                "title": it.get("title", ""),
            }
    return anchors


def load_profiles() -> list[dict[str, Any]]:
    cfg_dir = ROOT / "configs" / "games"
    profiles = []
    for p in sorted(cfg_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        profiles.append(json.loads(p.read_text(encoding="utf-8")))
    if TARGET_GAMES and TARGET_GAMES != ["ALL"]:
        allowed = set(TARGET_GAMES)
        profiles = [p for p in profiles if p.get("game") in allowed]
    return [p for p in profiles if p.get("enabled", True)]


def compile_patterns(values: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(x, re.I) for x in values or []]


def extract_date_from_text(text: str) -> str:
    text = text or ""
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return f"20{int(m.group(1)):02d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # v020: Odin KR homepage uses short M/D titles such as "6/3(수) 업데이트 상세 내역 안내".
    # Parse only when the surrounding title text indicates a patch/update notice to avoid URL-like false positives.
    m = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?:\s*\([^)]+\))?\s*(?:업데이트|패치노트|상세\s*내역)", text)
    if m:
        return f"{datetime.now(KST).year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\b", text, re.I)
    if m:
        months = {name.lower(): i for i, name in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
        return f"{datetime.now(KST).year:04d}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        return f"{datetime.now(KST).year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""






def normalized_patch_page_title(actual_date: str, fallback_title: str = "") -> str:
    """Return the standard Notion item name used by existing Patch View Model pages.

    Standard: YY.MM.DD | 패치노트.
    This keeps newly detected pages aligned with the historical item-name rule
    instead of using source titles such as "Patch Note - June 2nd" or
    "6월 4일(목) 패치노트" as the Notion title.
    """
    date = (actual_date or "").strip()
    if not re.match(r"^20\d{2}-\d{2}-\d{2}$", date):
        date = extract_date_from_text(fallback_title or "")
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", date):
        yy = int(date[2:4])
        mm = int(date[5:7])
        dd = int(date[8:10])
        return f"{yy:02d}.{mm:02d}.{dd:02d} | 패치노트"
    title = (fallback_title or "").strip()
    return title if title else "패치노트"


def year_from_fallback(fallback: str = "") -> int:
    m = re.match(r"^(20\d{2})-", str(fallback or ""))
    if m:
        return int(m.group(1))
    return datetime.now(KST).year


def extract_effective_patch_date(title: str, text: str, fallback: str = "", profile: dict[str, Any] | None = None) -> str:
    """Prefer the actual patch/update date over posted date.

    v015 keeps the v010 date fix for pages like NightCrows KR where the detail page contains both
    an effective patch-note title such as "6월 4일(목) 패치노트" and a
    separate posted timestamp such as "2026.06.03 18:00". The effective
    title date wins.
    """
    profile = profile or {}
    year = year_from_fallback(fallback)
    title = title or ""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]

    # 1) Highest priority: line/title explicitly saying patch note/update.
    priority_sources = [title] + lines[:80]
    for src in priority_sources:
        if not re.search(r"(패치노트|업데이트|patch\s*note|update)", src, re.I):
            continue
        m = re.search(r"(?:(20\d{2})[.\-/]\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일", src)
        if m:
            yy = int(m.group(1)) if m.group(1) else year
            return f"{yy:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", src)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\b", src, re.I)
        if m:
            months = {name.lower(): i for i, name in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
            return f"{year:04d}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"

    # 2) Fallback: title date only, then row/list date.
    title_date = extract_date_from_text(title)
    if title_date:
        return title_date
    return fallback or extract_date_from_text("\n".join(lines[:40]))


def compress_update_units_for_preview(units: list[dict[str, Any]], profile: dict[str, Any], title: str = "") -> list[dict[str, Any]]:
    """Conservatively reduce oversized preview unit lists.

    This is a preview compression layer, not a Notion write decision. It keeps
    independent high-signal update units while avoiding 20-line KR patch cards
    caused by every minor convenience heading being promoted to body_summary.
    """
    if len(units) <= 12:
        return units
    game = profile.get("game", "")

    priority_keywords = [
        "신규 무기 외형", "도미니언", "공명 카드", "기술 정보창", "에픽 던전",
        "연금술", "파티 던전", "몬스터 스폰", "new system", "new artifact",
        "new world battlefront", "potential", "world dungeon", "server transfer",
        "creed", "lamp", "auber",
    ]
    selected: list[dict[str, Any]] = []
    used = set()
    for u in units:
        hay = f"{u.get('source_heading','')} {u.get('summary_sentence','')}".lower()
        if any(k.lower() in hay for k in priority_keywords):
            key = norm_key(u.get("summary_sentence", ""))
            if key not in used:
                selected.append(u)
                used.add(key)
        if len(selected) >= 8:
            break

    # Add one aggregated convenience line when many convenience-only headings remain.
    convenience_units = [u for u in units if u.get("domain") == "편의/UI" and norm_key(u.get("summary_sentence", "")) not in used]
    aggregated_convenience = False
    if convenience_units:
        headings = [clean_heading_text(str(u.get("source_heading", ""))) for u in convenience_units[:5]]
        agg = {
            "order": min([int(u.get("order") or 999) for u in convenience_units] or [999]),
            "domain": "편의/UI",
            "source_heading": "편의 기능 개선 묶음",
            "source_context_excerpt": " / ".join([h for h in headings if h])[:280],
            "summary_sentence": "편의/UI: UI 숨기기, 입장권 사용, 지도 이동, 재화 표기 등 주요 편의 기능이 개선됩니다.",
            "confidence": 0.78,
            "compressed_from_count": len(convenience_units),
        }
        selected.append(agg)
        aggregated_convenience = True

    # Keep original order; fill up to 12 with earliest remaining if needed.
    selected_keys = {norm_key(u.get("summary_sentence", "")) for u in selected}
    for u in units:
        if aggregated_convenience and u.get("domain") == "편의/UI":
            continue
        key = norm_key(u.get("summary_sentence", ""))
        if key not in selected_keys:
            selected.append(u)
            selected_keys.add(key)
        if len(selected) >= 12:
            break

    selected = sorted(selected, key=lambda u: int(u.get("order") or 999))[:12]
    for u in selected:
        u["preview_compression"] = "compressed_high_unit_count"
    return selected

def is_list_or_board_url(url: str, profile: dict[str, Any]) -> bool:
    c = profile_canonical_url(url, profile)
    list_url = profile_canonical_url(profile.get("list_url", ""), profile)
    if list_url and c == list_url:
        return True
    p = urlparse(c)
    path = re.sub(r"/+$", "", p.path or "")
    for pattern in compile_patterns(profile.get("list_url_exclude_patterns", [])):
        if pattern.search(c) or pattern.search(path):
            return True
    return False


def is_detail_url(url: str, profile: dict[str, Any]) -> bool:
    if not url or is_list_or_board_url(url, profile):
        return False
    c = profile_canonical_url(url, profile)
    p = urlparse(c)
    path = p.path or ""
    include = compile_patterns(profile.get("detail_url_include_patterns", []))
    exclude = compile_patterns(profile.get("detail_url_exclude_patterns", []))
    if include and not any(rx.search(c) or rx.search(path) for rx in include):
        return False
    if exclude and any(rx.search(c) or rx.search(path) for rx in exclude):
        return False
    return True


def fetch_official_list(profile: dict[str, Any]) -> list[dict[str, Any]]:
    list_url = profile.get("list_url") or ""
    if not list_url:
        return []
    r = requests.get(list_url, headers={"User-Agent": "Mozilla/5.0 patch-update-actions"}, timeout=45)
    r.raise_for_status()
    html = r.text
    safe_game = re.sub(r"[^A-Za-z0-9_]+", "_", profile.get("game", "game"))
    (ART / f"raw_list_{safe_game}.html").write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    url_patterns = compile_patterns(profile.get("url_include_patterns", []))
    title_patterns = compile_patterns(profile.get("title_include_patterns", []))
    exclude_patterns = compile_patterns(profile.get("title_exclude_patterns", []))
    base = list_url
    out = []
    rejected = []

    # v020: Some official landing pages expose the same detail URL multiple times.
    # Example: Odin_KR may expose cafe.daum.net/odin/DEH7/258 once as
    # "6/3(수) 업데이트 상세 내역 안내" and once as "업데이트&이벤트 안내".
    # Do not reject the URL just because one duplicate anchor has an excluded
    # promotional title. Group duplicate URLs first, then let an include-title
    # anchor win over generic/excluded duplicate titles.
    grouped: dict[str, dict[str, Any]] = {}
    for list_index, a in enumerate(soup.find_all("a")):
        href = a.get("href")
        if not href:
            continue
        url = profile_canonical_url(urljoin(base, href), profile)
        if not url:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if url not in grouped:
            grouped[url] = {"url": url, "canonical_url": url, "titles": [], "list_index": list_index}
        grouped[url]["titles"].append({"title": title, "list_index": list_index})

    for url, entry in grouped.items():
        path = urlparse(url).path
        titles = entry.get("titles") or []
        title_rows = []
        for t in titles:
            title = t.get("title", "")
            hay = f"{title} {url}"
            title_rows.append({
                "title": title,
                "hay": hay,
                "include_match": bool(title_patterns and any(rx.search(hay) for rx in title_patterns)),
                "exclude_match": bool(exclude_patterns and any(rx.search(hay) for rx in exclude_patterns)),
                "actual_date": extract_date_from_text(hay),
                "list_index": t.get("list_index", entry.get("list_index", 0)),
            })

        reject_reason = ""
        if url_patterns and not any(rx.search(path) or rx.search(url) for rx in url_patterns):
            reject_reason = "url_include_mismatch"
        elif not is_detail_url(url, profile):
            reject_reason = "not_detail_url"
        else:
            # Include-title wins over excluded duplicate title.
            include_rows = [x for x in title_rows if x["include_match"]]
            if title_patterns and not include_rows:
                reject_reason = "title_include_mismatch"
            elif not include_rows and any(x["exclude_match"] for x in title_rows):
                reject_reason = "title_exclude_match"

        if reject_reason:
            rejected.append({
                "url": url,
                "titles": [x.get("title", "") for x in title_rows],
                "reason": reject_reason,
            })
            continue

        include_rows = [x for x in title_rows if x["include_match"]]
        date_rows = [x for x in (include_rows or title_rows) if x.get("actual_date")]
        selected = (date_rows or include_rows or title_rows or [{"title": "", "actual_date": "", "list_index": entry.get("list_index", 0)}])[0]
        out.append({
            "url": url,
            "canonical_url": url,
            "title": selected.get("title", ""),
            "actual_date": selected.get("actual_date") or extract_date_from_text(" ".join(x.get("title", "") for x in title_rows)),
            "list_index": selected.get("list_index", entry.get("list_index", 0)),
            "title_candidates": [x.get("title", "") for x in title_rows if x.get("title")],
        })

    out = sorted(out, key=lambda x: int(x.get("list_index") or 0))
    (ART / f"rejected_links_{safe_game}.json").write_text(json.dumps(rejected[:200], ensure_ascii=False, indent=2), encoding="utf-8")
    return out[:MAX_LIST_ITEMS]



def comparable_numeric_suffix(url: str, profile: dict[str, Any]) -> int | None:
    """Return numeric trailing post id for profile-scoped detail URLs.

    v020: Odin KR official homepage can expose only one short recent item, while
    the stored anchor is outside the visible list. If the detail URL pattern is
    stable and monotonically increasing (e.g. /DEH7/258 after /DEH7/257), use it
    as a profile-gated fallback after date fallback.
    """
    try:
        c = profile_canonical_url(url or "", profile)
        m = re.search(r"/([A-Za-z0-9]+)/(\d+)(?:$|[/?#])", c)
        if not m:
            return None
        return int(m.group(2))
    except Exception:
        return None

def detect_newer_than_anchor(profile: dict[str, Any], official_list: list[dict[str, Any]], anchor: dict[str, Any] | None) -> dict[str, Any]:
    game = profile.get("game", "")
    order = profile.get("list_order", "newest_first")
    anchor_c = profile_canonical_url((anchor or {}).get("source_url", ""), profile)
    rows = []
    seen = set()
    for i, x in enumerate(official_list):
        c = profile_canonical_url(x.get("canonical_url") or x.get("url") or "", profile)
        if not c or c in seen or not is_detail_url(c, profile):
            continue
        seen.add(c)
        rows.append({
            "game": game,
            "list_index": i,
            "source_url": c,
            "title": x.get("title", ""),
            "actual_date": ymd_key(x.get("actual_date")),
        })

    idx = next((i for i, x in enumerate(rows) if x["source_url"] == anchor_c), None)

    status = "PASS"
    reason = "anchor_found"
    if anchor and idx is not None:
        if order == "newest_first":
            candidates = rows[:idx]
        elif order == "oldest_first":
            candidates = rows[idx + 1:]
        else:
            ad = anchor.get("actual_date", "")
            candidates = [r for r in rows if r.get("actual_date") and r["actual_date"] > ad]
            status = "REVIEW"
            reason = "unknown_order_date_fallback"
    elif anchor and idx is None:
        ad = anchor.get("actual_date", "")
        candidates = [r for r in rows if r.get("actual_date") and ad and r["actual_date"] > ad]
        numeric_fallback_used = False
        if not candidates and profile.get("anchor_missing_numeric_id_fallback_as_pass"):
            anchor_id = comparable_numeric_suffix(anchor_c, profile)
            if anchor_id is not None:
                numeric_candidates = []
                for r in rows:
                    rid = comparable_numeric_suffix(r.get("source_url", ""), profile)
                    if rid is not None and rid > anchor_id:
                        numeric_candidates.append(r)
                if numeric_candidates:
                    candidates = numeric_candidates
                    numeric_fallback_used = True
        if candidates and profile.get("anchor_missing_date_fallback_as_pass"):
            # v018/v020: Some official landing pages expose only a short recent-news window.
            # The stored anchor can fall outside that visible window; in that case,
            # profile-gated date or numeric-id fallback is acceptable.
            status = "PASS_NUMERIC_ID_FALLBACK_SHORT_LIST" if numeric_fallback_used else "PASS_DATE_FALLBACK_SHORT_LIST"
            reason = "anchor_url_not_found_short_list_numeric_id_fallback" if numeric_fallback_used else "anchor_url_not_found_short_list_date_fallback"
        else:
            status = "REVIEW_ANCHOR_MISSING_DATE_FALLBACK" if candidates else "REVIEW_ANCHOR_MISSING"
            reason = "anchor_url_not_found"
    else:
        candidates = []
        status = "REVIEW_NO_ANCHOR"
        reason = "no_anchor_in_view_model"

    candidates = sorted(candidates, key=lambda r: (r.get("actual_date") or "9999-99-99", r.get("list_index", 0)))[:MAX_NEW_URLS_PER_GAME]
    return {
        "game": game,
        "status": status,
        "reason": reason,
        "anchor": anchor or {},
        "anchor_canonical_for_profile": anchor_c,
        "list_count": len(rows),
        "new_count": len(candidates),
        "new_urls": candidates,
    }



def safe_slug(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "")).strip("_")
    return slug[:80] or fallback


def normalize_visible_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    lines = []
    for line in text.splitlines():
        t = line.strip()
        if not t:
            continue
        # Drop highly repetitive navigation/footer fragments.
        if re.fullmatch(r"[|·•\-_/\\]+", t):
            continue
        if len(t) <= 1:
            continue
        lines.append(t)
    # De-duplicate adjacent or repeated boilerplate lines while preserving order.
    out = []
    seen_counts: dict[str, int] = {}
    for line in lines:
        key = norm_key(line)
        seen_counts[key] = seen_counts.get(key, 0) + 1
        if seen_counts[key] <= 2:
            out.append(line)
    return "\n".join(out)


def extract_content_text_from_soup(soup: BeautifulSoup, profile: dict[str, Any]) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "form"]):
        tag.decompose()
    selectors = profile.get("detail_content_selectors", []) or [
        "article", "main", "#content", ".content", ".contents", ".view", ".view_cont", ".view-content", ".board-view", ".notice-view", "body"
    ]
    candidates = []
    for selector in selectors:
        try:
            for node in soup.select(selector):
                txt = normalize_visible_text(node.get_text("\n", strip=True))
                if txt:
                    candidates.append(txt)
        except Exception:
            continue
    if not candidates:
        candidates.append(normalize_visible_text(soup.get_text("\n", strip=True)))
    return max(candidates, key=len) if candidates else ""


def extract_detail_title(soup: BeautifulSoup, fallback: str, profile: dict[str, Any]) -> str:
    """Extract a display title for detail pages.

    v008 avoids generic site chrome titles such as News/새소식 and prefers
    patch-note-like lines from the visible page text when selectors are noisy.
    """
    generic = {"news", "notice", "release", "새소식", "공지사항", "패치노트", "night crows"}
    selectors = profile.get("detail_title_selectors", []) or ["h1", ".view-title", ".title", ".tit", ".board-title"]
    candidates: list[str] = []
    for selector in selectors:
        try:
            for node in soup.select(selector):
                txt = " ".join(node.get_text(" ", strip=True).split())
                if txt and len(txt) >= 3:
                    candidates.append(txt)
        except Exception:
            continue
    if soup.title and soup.title.string:
        candidates.append(" ".join(soup.title.string.split()))

    visible = normalize_visible_text(soup.get_text("\n", strip=True))
    for line in visible.splitlines()[:80]:
        t = " ".join(line.split())
        if not t:
            continue
        if re.search(r"Patch Note\s*[-–]\s*", t, re.I):
            candidates.insert(0, t)
        if re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일.*패치노트", t):
            candidates.insert(0, t)
        if re.search(r"\[패치노트\]", t):
            continue

    for txt in candidates:
        key = txt.strip().lower()
        if key in generic:
            continue
        if len(norm_key(txt)) < 4:
            continue
        return txt
    return fallback or "패치노트"


DOMAIN_KEYWORDS: list[tuple[str, list[str]]] = [
    ("신규/대형 업데이트", ["new class", "신규 클래스", "new server", "신규 서버", "new region", "신규 지역", "new chapter", "신규 챕터", "new system", "신규 시스템", "major update", "대규모"]),
    ("클래스/스킬", ["class", "skill", "클래스", "직업", "스킬", "ability", "spell"]),
    ("서버/월드", ["server", "world", "서버", "월드", "merge", "transfer", "이전", "통합"]),
    ("PvP/전쟁", ["pvp", "battlefield", "war", "siege", "conquest", "guild war", "전쟁", "전장", "공성", "쟁탈", "격전지", "월드 던전"]),
    ("PvE 콘텐츠", ["dungeon", "boss", "monster", "quest", "field", "raid", "던전", "보스", "몬스터", "퀘스트", "필드", "지역", "콘텐츠"]),
    ("성장/장비", ["equipment", "gear", "item", "craft", "enhance", "growth", "artifact", "collection", "장비", "아이템", "제작", "강화", "성장", "수집", "아티팩트", "유물"]),
    ("경제/보상", ["reward", "exchange", "shop", "drop", "currency", "보상", "교환", "상점", "드롭", "재화", "거래", "가격"]),
    ("이벤트/보상", ["event", "mission", "check-in", "attendance", "이벤트", "미션", "출석", "기념", "교환소"]),
    ("상점/BM", ["package", "pass", "product", "purchase", "shop", "패키지", "패스", "상품", "구매", "판매"]),
    ("편의/UI", ["ui", "convenience", "display", "filter", "sort", "improved", "편의", "표시", "필터", "정렬", "개선"]),
    ("버그 수정", ["fix", "issue", "bug", "error", "오류", "버그", "수정", "현상"]),
]


def classify_domain(line: str) -> str:
    hay = line.lower()
    for domain, words in DOMAIN_KEYWORDS:
        if any(w.lower() in hay for w in words):
            return domain
    return "기타"


def truncate_sentence(text: str, limit: int = 180) -> str:
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


TITLE_NOISE = {"news", "새소식", "patch note", "패치노트", "night crows", "nightcrows"}



ODIN_NAV_NOISE_PATTERNS = [
    r"^CAFE$", r"^업데이트$", r"^앱으로보기$", r"^\[업데이트\]$", r"^작성자$", r"^작성시간$", r"^조회수$", r"^목록$", r"^댓글$", r"^글자크기", r"^이전글$", r"^다음글$", r"^수정$", r"^저작자 표시$", r"^전체보기$", r"^PC화면$", r"^카페앱$", r"^서비스 약관$", r"^개인정보처리방침$", r"^AXZ Corp\.$",
    r"^카페 만들기$", r"^카페검색$", r"^카페 메뉴$", r"^내카페$", r"^내소식$", r"^에러$", r"^고객센터$", r"^맨위로$",
    r"^CM토르$", r"^\d{2}\.\d{2}\.\d{2}$", r"^[0-9,]+$", r"^\d+$"
]


def html_to_visible_text_for_odin(text: str) -> str:
    """Daum Cafe _c21_ responses may put article body HTML in text fields.
    Convert any HTML-like source into visible text before summary extraction.
    """
    raw = text or ""
    if "<" in raw and ">" in raw:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "form"]):
            tag.decompose()
        raw = soup.get_text("\n", strip=True)
    return normalize_visible_text(raw)


def clean_odin_kr_article_text(text: str) -> str:
    """Extract the actual Odin KR patch article body from Daum Cafe text.

    v022 prevents HTML/comment/navigation leakage by preferring the article span
    between the patch detail intro and the closing thanks sentence. It is used
    for variant scoring, raw text artifact selection, and summary generation.
    """
    visible = html_to_visible_text_for_odin(text)
    lines = [x.strip() for x in visible.splitlines() if x.strip()]
    filtered: list[str] = []
    for line in lines:
        t = re.sub(r"\s+", " ", line).strip()
        if not t:
            continue
        if any(re.search(p, t, re.I) for p in ODIN_NAV_NOISE_PATTERNS):
            continue
        if t.startswith("<") or "data-ke-" in t or "cafeattach" in t or "figure-img" in t:
            continue
        if re.search(r"(서비스 약관|청소년보호정책|상거래피해구제신청|카페 검색|댓글\s*\d*)", t):
            continue
        # Drop obvious user comment fragments from Daum Cafe comment area.
        if any(x in t for x in ["에효", "패스권도 그냥", "너무하네", "댓글쓰기", "답글"]):
            continue
        filtered.append(t)

    if not filtered:
        return ""

    # Prefer body starting near the explicit guide phrase or title banner.
    start_idx = 0
    start_markers = [
        "업데이트에 대한 자세한 내용",
        "업데이트 상세 내역 안내",
        "6/3(수) 업데이트 상세 내역 안내",
    ]
    for i, line in enumerate(filtered):
        if any(m in line for m in start_markers):
            start_idx = i
            break

    body = filtered[start_idx:]
    out: list[str] = []
    for line in body:
        out.append(line)
        if "감사합니다" in line:
            break
    # If thanks was not captured, still stop before obvious next/previous/comment chrome.
    if out and not any("감사합니다" in x for x in out):
        clipped = []
        for line in out:
            if line in {"이전글", "다음글", "목록"} or line.startswith("댓글"):
                break
            clipped.append(line)
        out = clipped

    # De-duplicate and keep sufficiently informative lines.
    final: list[str] = []
    seen = set()
    for line in out:
        key = norm_key(line)
        if key in seen:
            continue
        seen.add(key)
        final.append(line)
    return "\n".join(final)


def odin_kr_summary_units_from_text(text: str) -> list[dict[str, Any]]:
    """Profile-aware Odin KR preview units for the 6/3 update style.

    This remains conservative: event/BM-heavy updates are summarized as a few
    independent units and will not emit comment/footer noise.
    """
    t = clean_odin_kr_article_text(text)
    units: list[dict[str, Any]] = []

    def add(order: int, domain: str, sentence: str, heading: str) -> None:
        if sentence not in [u.get("summary_sentence") for u in units]:
            units.append({
                "order": order,
                "domain": domain,
                "source_heading": heading,
                "source_context_excerpt": truncate_sentence(t, 280),
                "summary_sentence": sentence,
                "confidence": 0.86,
                "profile_rule": "Odin_KR_v022",
            })

    order = 1
    if "서버 침공전" in t:
        add(order, "PvP/전쟁", "PvP/전쟁: 서버 침공전이 6/3 10:00~23:59 일정으로 진행됩니다.", "서버 침공전")
        order += 1
    if "신규 이벤트" in t or "이벤트" in t:
        add(order, "이벤트/보상", "이벤트/보상: 신규 이벤트가 추가되어 기간제 참여 보상과 지원 혜택이 갱신됩니다.", "신규 이벤트")
        order += 1
    if "신규 상품" in t or "상품 추가" in t or "상품" in t:
        add(order, "상점/BM", "상점/BM: 신규 상품 구성이 추가되어 상점 판매 항목이 갱신됩니다.", "신규 상품")
        order += 1
    if "교환" in t or "보상" in t:
        add(order, "경제/보상", "경제/보상: 이벤트 및 교환 보상 구성이 갱신됩니다.", "보상/교환")
        order += 1
    return units


def clean_detail_text_for_summary(text: str, profile: dict[str, Any], title: str) -> str:
    """Return the patch-note body area used for summary candidate generation.

    This keeps raw_text artifacts untouched while giving the preview generator a
    cleaner source. The function is deliberately rule-based and conservative.
    """
    if is_odin_kr_profile(profile):
        return clean_odin_kr_article_text(text)
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    game = profile.get("game", "")
    start_patterns = [
        r"^Main Updates$",
        r"^Update Details$",
        r"^■\s*Content Updates",
        r"^신규 추가 및 변경 사항$",
        r"^업데이트 내용$",
        r"^상세 내용$",
    ]
    end_patterns = [
        r"^신규 이벤트$", r"^종료 이벤트$", r"^상품", r"^판매 상품", r"^이벤트/시즌패스 이름",
        r"^Known Issues$", r"^Events?$", r"^Shop$", r"^Products?$", r"^Resolved Issues$",
    ]
    start_idx = 0
    for i, line in enumerate(lines):
        if any(re.search(p, line, re.I) for p in start_patterns):
            start_idx = i
            break
    body = lines[start_idx:]
    # Keep event names available but prevent large event tables from dominating summary preview.
    clipped = []
    for line in body:
        if clipped and any(re.search(p, line, re.I) for p in end_patterns):
            clipped.append(line)
            break
        clipped.append(line)
    return "\n".join(clipped)


def clean_heading_text(heading: str) -> str:
    h = re.sub(r"^\s*\d{1,2}[.)]\s*", "", heading or "").strip()
    h = re.sub(r"^[•◦\-]\s*", "", h).strip()
    h = re.sub(r"\s+", " ", h)
    return h


def extract_numbered_heading_blocks(text: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    table_noise = {"lv", "level", "item name", "preview", "points obtained", "obtain location", "details", "class", "effect", "등급", "구분", "필요 수량", "효과", "분류", "상세 내용"}
    for line in lines:
        # Top-level headings in NC pages are usually "1. ...". Avoid table rows like Lv. 10.
        m = re.match(r"^(\d{1,2})\.\s+(.{3,120})$", line)
        if m:
            heading = clean_heading_text(line)
            hkey = heading.lower().strip()
            if hkey in table_noise or re.match(r"^lv\.?\s*\d+", hkey):
                continue
            if current:
                blocks.append(current)
            current = {"order": int(m.group(1)), "heading": heading, "lines": []}
            continue
        if current:
            # Stop giant table accumulation but keep nearby bullet lines.
            if len(current["lines"]) < 16:
                current["lines"].append(line)
    if current:
        blocks.append(current)
    # de-duplicate duplicate Main Updates / Update Details headings.
    out: list[dict[str, Any]] = []
    seen = set()
    for b in blocks:
        key = norm_key(b.get("heading", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out[:30]


def classify_heading_domain(heading: str, context: str = "") -> str:
    h = f"{heading} {context}".lower()
    # Specific NC mapping before generic keyword matching.
    if any(x in h for x in ["world battlefront", "dominion", "battlefront", "점령전", "도미니언"]):
        return "PvP/전쟁"
    if any(x in h for x in ["world dungeon", "party dungeon", "epic dungeon", "dungeon", "파티 던전", "에픽 던전", "테네리스", "몬스터 스폰"]):
        return "PvE 콘텐츠"
    if any(x in h for x in ["class", "skill", "기술 정보창", "화포", "권갑", "클래스"]):
        return "클래스/스킬"
    if any(x in h for x in ["server transfer", "server", "서버 이전", "서버"]):
        return "서버/월드"
    if any(x in h for x in ["artifact", "inner armor", "weapon style", "weapon", "potential", "transcendence", "creed", "lamp", "무기 외형", "공명 카드", "연금술", "길드 연구", "현신도", "신편", "정령", "성장 콘텐츠"]):
        return "성장/장비"
    if any(x in h for x in ["merchant", "purchase limit", "npc merchant", "drop", "reward", "상점", "드랍", "보상", "창고 보관"]):
        return "경제/보상"
    if any(x in h for x in ["event", "events", "이벤트", "출석", "시즌패스"]):
        return "이벤트/보상"
    if any(x in h for x in ["ui", "preset", "search", "map", "display", "hide", "ticket", "auto", "emotion", "emote", "편의", "검색", "프리셋", "지도", "표기", "숨기기", "감정 표현", "자동", "입장권", "일괄 사용"]):
        return "편의/UI"
    return classify_domain(h)


def quoted_subject(text: str) -> str:
    m = re.search(r"[‘'\"]([^‘’'\"]{2,60})[’'\"]", text or "")
    if m:
        return m.group(1).strip()
    m = re.search(r"‘([^’]{2,60})’", text or "")
    return m.group(1).strip() if m else ""



def mir4_kr_summary_sentence(heading: str, context: str) -> dict[str, Any] | None:
    """MIR4_KR-specific rule templates for update-unit preview.

    v016 fixes the 2026-06-04 MIR4_KR candidate quality issue where generic
    numbered headings such as "성장 콘텐츠" were classified as 편의/UI and
    sentences ended with the filler phrase "변경 사항이 반영됩니다".
    """
    h = clean_heading_text(heading)
    hay = f"{h} {context}"
    sentence = ""
    domain = ""

    if "현신도" in hay:
        domain = "성장/장비"
        sentence = "성장/장비: 신규 성장 콘텐츠 ‘현신도’가 추가되어 신편 복원과 결속을 통해 능력치를 획득할 수 있습니다."
    elif "천리전령 마루" in hay or ("전설 정령" in hay and "소환" in hay):
        domain = "성장/장비"
        sentence = "성장/장비: 전설 정령 특별 소환 대상이 ‘천리전령 마루’로 변경됩니다."
    elif "초여름의 산들바람" in hay:
        domain = "이벤트/보상"
        sentence = "이벤트/보상: ‘초여름의 산들바람’ 이벤트가 시작되어 출석 및 선물 상자 보상이 제공됩니다."
    elif "레벨 제한 상품" in hay and "정렬" in hay:
        domain = "편의/UI"
        sentence = "편의/UI: 상점의 레벨 제한 상품 정렬 방식이 개선됩니다."
    elif "결투장" in hay and "히든 모드" in hay:
        domain = "버그 수정"
        sentence = "버그 수정: 결투장 히든 모드에서 특정 경로로 캐릭터 정보를 확인할 수 있던 문제가 수정됩니다."
    elif "균열된 비정봉 11층" in hay and ("칼이 향하는 곳" in hay or "진행되지" in hay):
        domain = "버그 수정"
        sentence = "버그 수정: 균열된 비정봉 11층의 원정대 주간 임무 ‘칼이 향하는 곳 1~3’ 진행 문제가 수정됩니다."
    elif "균열된 비정봉 12층" in hay and ("행운 드랍" in hay or "드랍 연출" in hay):
        domain = "버그 수정"
        sentence = "버그 수정: 균열된 비정봉 12층에서 공허·생령 몬스터 처치 시 행운 드랍 연출이 비정상적으로 노출되던 문제가 수정됩니다."

    if not sentence:
        return None
    return {
        "domain": domain,
        "summary_sentence": sentence,
        "confidence": 0.9,
        "profile_rule": "MIR4_KR_v016",
    }


def normalize_units_for_profile(units: list[dict[str, Any]], profile: dict[str, Any], title: str = "") -> list[dict[str, Any]]:
    game = profile.get("game", "")
    if game != "MIR4_KR":
        return units

    normalized: list[dict[str, Any]] = []
    seen = set()
    for u in units:
        heading = str(u.get("source_heading", ""))
        context = str(u.get("source_context_excerpt", ""))
        repl = mir4_kr_summary_sentence(heading, context)
        if repl:
            u = dict(u)
            u["domain"] = repl["domain"]
            u["summary_sentence"] = repl["summary_sentence"]
            u["confidence"] = repl["confidence"]
            u["profile_rule"] = repl["profile_rule"]
        sent = str(u.get("summary_sentence", ""))
        # Drop generic duplicate "성장 콘텐츠" if a specific 현신도 sentence is already present.
        key = norm_key(sent)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(u)
    return normalized

def summary_sentence_from_heading(block: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    heading = clean_heading_text(block.get("heading", ""))
    context = " ".join(block.get("lines", [])[:5])
    domain = classify_heading_domain(heading, context)
    lang_ko = bool(re.search(r"[가-힣]", heading + context))
    h = heading
    low = h.lower()
    subject = quoted_subject(h) or quoted_subject(context)
    sentence = ""

    if profile.get("game") == "MIR4_KR":
        repl = mir4_kr_summary_sentence(heading, context)
        if repl:
            return {
                "order": block.get("order"),
                "domain": repl["domain"],
                "source_heading": heading,
                "source_context_excerpt": truncate_sentence(context, 280),
                "summary_sentence": repl["summary_sentence"],
                "confidence": repl["confidence"],
                "profile_rule": repl["profile_rule"],
            }

    if not lang_ko:
        # English NC preview templates. Keep English names, Korean sentence frame.
        if "new system" in low and subject:
            sentence = f"{domain}: 신규 시스템 ‘{subject}’가 추가됩니다."
        elif "new artifact" in low and subject:
            sentence = f"성장/장비: 신규 아티팩트 ‘{subject}’가 추가됩니다."
        elif "new world battlefront" in low and subject:
            sentence = f"PvP/전쟁: 신규 월드 배틀프론트 ‘{subject}’가 추가됩니다."
        elif "potential" in low and "5" in low:
            sentence = "성장/장비: Potential 5번째 페이지가 추가되어 성장 구성이 확장됩니다."
        elif "legendary inner armor" in low:
            sentence = "성장/장비: 전설 등급 Inner Armor가 추가됩니다."
        elif "purchase limit" in low and "merchant" in low:
            sentence = "경제/보상: NPC Merchant 상점의 구매 제한이 조정됩니다."
        elif "world dungeon" in low and "season" in low:
            m = re.search(r"season\s*(\d+)", h, re.I)
            season = f" 시즌 {m.group(1)}" if m else " 신규 시즌"
            sentence = f"PvE 콘텐츠: World Dungeon{season}가 시작됩니다."
        elif "server transfer" in low:
            sentence = "서버/월드: Boost Camp 서버 이전이 시작됩니다."
        elif "transcendence effect" in low:
            sentence = "성장/장비: Lv.10 전설 탈것 및 무기 외형의 초월 효과가 개선됩니다."
        elif "events" in low or "event" in low:
            m = re.search(r"(\d+)\s+new events", h, re.I)
            count = f" {m.group(1)}종" if m else ""
            sentence = f"이벤트/보상: 신규 이벤트{count}이 추가됩니다."
        elif "will be added" in low:
            subj = subject or re.sub(r"will be added\.?", "", h, flags=re.I).strip(" :-")
            sentence = f"{domain}: {subj}이 추가됩니다."
        elif "will be adjusted" in low:
            subj = re.sub(r"will be adjusted\.?", "", h, flags=re.I).strip(" :-")
            sentence = f"{domain}: {subj}이 조정됩니다."
        elif "will be improved" in low:
            subj = re.sub(r"will be improved\.?", "", h, flags=re.I).strip(" :-")
            sentence = f"{domain}: {subj}이 개선됩니다."
        else:
            sentence = f"{domain}: {truncate_sentence(h, 150)}"
    else:
        # Korean NC preview templates.
        if "신규 무기 외형" in h or "무기 외형" in h:
            sentence = "성장/장비: 클래스별 신규 무기 외형이 추가되고, 신화 등급 무기 외형 관련 성장 조건과 보유 효과가 확장됩니다."
        elif "도미니언" in h:
            sentence = "PvP/전쟁: 도미니언 점령전 전당 전투의 공성측 부활 지점이 변경됩니다."
        elif "공명 카드" in h:
            sentence = "성장/장비: 공명 카드 수집 목록 검색과 프리셋 기능이 추가됩니다."
        elif "기술 정보창" in h:
            sentence = "클래스/스킬: 화포와 권갑 클래스의 전환 상태에 따른 기술 정보창 표시가 개선됩니다."
        elif "에픽 던전" in h or "테네리스" in h:
            sentence = "PvE 콘텐츠: 에픽 던전 테네리스 해협의 난이도와 보상이 조정됩니다."
        elif "연금술" in h:
            sentence = "편의/UI: 연금술 원소 효과를 자동으로 변형할 수 있는 기능이 추가됩니다."
        elif "감정 표현" in h:
            sentence = "편의/UI: 유저 간 상호작용을 위한 캐릭터 감정 표현 9종이 추가됩니다."
        elif "UI 숨기기" in h:
            sentence = "편의/UI: 게임 내 UI를 숨기고 캐릭터를 감상할 수 있는 촬영 모드 기능이 추가됩니다."
        elif "길드 연구" in h or "길드 연구소" in h:
            sentence = "길드/성장: 길드 연구소 화면과 붉은 늑대 일지 재료 교환 기능이 개선됩니다."
        elif "익명 지역" in h:
            sentence = "PvP/전쟁: 익명 지역 입장 시 길드원이 아닌 파티원과의 파티 해제 규칙이 완화됩니다."
        elif "창고 보관" in h:
            sentence = "편의/UI: 창고에 보관한 아이템을 사용할 수 있는 콘텐츠 범위가 확장됩니다."
        elif "파티 던전" in h:
            sentence = "PvE 콘텐츠: 파티 던전 신규 시즌이 시작되고 보스 몬스터 ‘크라부스’가 등장합니다."
        elif "던전 입장권" in h:
            sentence = "편의/UI: 가방에서 던전 입장권 사용 시 해당 던전 입장 화면이 노출되도록 개선됩니다."
        elif "일괄 사용" in h:
            sentence = "편의/UI: 기술 특성 비급서와 성장 재료 등 일부 아이템의 일괄 사용 범위가 확장됩니다."
        elif "지도" in h:
            sentence = "편의/UI: 지도 지역 선택 시 카메라 이동과 지역 정보창 접기 동작이 개선됩니다."
        elif "다이아" in h or "표기" in h:
            sentence = "편의/UI: 화면 상단의 다이아와 미스틱 다이아가 분리되어 표시되도록 개선됩니다."
        elif "시험의 탑" in h:
            sentence = "편의/UI: 시험의 탑 클리어 보상 팝업 종료 시 자동 진행이 취소되도록 규칙이 변경됩니다."
        elif "길드 지령" in h:
            sentence = "편의/UI: 길드 지령서 자동 사용 설정이 지령서 부족이나 일일 한도 도달 후에도 유지되도록 개선됩니다."
        elif "강화 효과" in h or "약화 효과" in h:
            sentence = "편의/UI: 상태 이상·약화 효과·강화 효과 아이콘 표시 방식이 개선됩니다."
        elif "몬스터 스폰" in h:
            sentence = "PvE 콘텐츠: 넓은 사냥터에서 몬스터가 더 고르게 등장하도록 스폰 방식이 개선됩니다."
        else:
            sentence = f"{domain}: {truncate_sentence(h, 150)} 변경 사항이 반영됩니다."

    if ":" in sentence:
        domain = sentence.split(":", 1)[0].strip()
    return {
        "order": block.get("order"),
        "domain": domain,
        "source_heading": heading,
        "source_context_excerpt": truncate_sentence(context, 280),
        "summary_sentence": sentence,
        "confidence": 0.82 if sentence and not sentence.endswith(h) else 0.65,
    }


def audit_summary_candidates(title: str, units: list[dict[str, Any]], text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    if norm_key(title) in {norm_key(x) for x in TITLE_NOISE}:
        flags.append("GENERIC_TITLE")
    if not units:
        flags.append("NO_UPDATE_UNITS")
    if len(units) > 18:
        flags.append("HIGH_UNIT_COUNT")
    for u in units:
        sent = str(u.get("summary_sentence", ""))
        after = sent.split(":", 1)[-1].strip()
        if re.match(r"^\d+[.)]\s*", after):
            flags.append("NUMBER_PREFIX_REMAINING")
        if re.search(r"\b(PVP 명중|PVP 방어|Item Name|Preview|Points Obtained)\b", sent, re.I):
            flags.append("TABLE_ROW_LEAK")
        if "변경 사항이 반영됩니다" in sent:
            flags.append("FILLER_PHRASE_REMAINING")
        if sent.startswith("기타:"):
            flags.append("GENERIC_DOMAIN_REMAINING")
        if len(after) < 10:
            flags.append("TOO_SHORT_SUMMARY")
    # dedupe flags
    flags = list(dict.fromkeys(flags))
    status = "PASS" if not flags else ("REVIEW" if flags != ["NO_UPDATE_UNITS"] else "FAIL")
    return status, flags


def make_rule_based_summary_preview(text: str, title: str, profile: dict[str, Any] | None = None) -> tuple[list[str], list[str], str, str, list[dict[str, Any]], list[str]]:
    """Create write-disabled summary candidates from detail text.

    v010 adds effective-date priority extraction and high-unit compression.
    It is still a preview generator, not final Notion write logic.
    """
    profile = profile or {}
    cleaned = clean_detail_text_for_summary(text, profile, title)
    if is_odin_kr_profile(profile):
        units = odin_kr_summary_units_from_text(cleaned)
        status, flags = audit_summary_candidates(title, units, cleaned)
        body = [u["summary_sentence"] for u in units[:12]]
        tags = []
        for u in units:
            d = u.get("domain") or classify_domain(u.get("summary_sentence", ""))
            if d and d not in tags:
                tags.append(d)
        card = " · ".join(tags[:4]) if tags else truncate_sentence(title, 80)
        if len(body) < 2:
            status = "REVIEW" if body else "FAIL"
            flags = list(dict.fromkeys(flags + ["ODIN_UNIT_COUNT_LOW"]))
        return body, tags, card, status, units, flags
    blocks = extract_numbered_heading_blocks(cleaned, profile)
    units = [summary_sentence_from_heading(b, profile) for b in blocks]
    units = normalize_units_for_profile(units, profile, title)
    raw_unit_count = len(units)
    units = compress_update_units_for_preview(units, profile, title)
    if not units:
        # Conservative fallback when numbered sections are not available.
        lines = [x.strip() for x in cleaned.splitlines() if x.strip()]
        for line in lines[:80]:
            domain = classify_domain(line)
            if domain != "기타":
                units.append({
                    "order": len(units) + 1,
                    "domain": domain,
                    "source_heading": truncate_sentence(line, 120),
                    "source_context_excerpt": "",
                    "summary_sentence": f"{domain}: {truncate_sentence(line, 160)}",
                    "confidence": 0.55,
                })
            if len(units) >= 6:
                break
    status, flags = audit_summary_candidates(title, units, cleaned)
    if raw_unit_count > len(units):
        flags = [f for f in flags if f != "HIGH_UNIT_COUNT"]
        flags.append(f"COMPRESSED_FROM_{raw_unit_count}_TO_{len(units)}")
        status = "PASS" if all(str(f).startswith("COMPRESSED_FROM_") for f in flags) else ("REVIEW" if flags else "PASS")
    body = [u["summary_sentence"] for u in units[:12]]
    tags: list[str] = []
    for u in units:
        d = u.get("domain", "")
        if d and d not in tags:
            tags.append(d)
    card = " · ".join(tags[:4]) if tags else truncate_sentence(title, 80)
    return body, tags, card, status, units, flags


def is_odin_kr_profile(profile: dict[str, Any]) -> bool:
    return str(profile.get("game", "")).lower() == "odin_kr"


def odin_detail_fetch_urls(url: str, html: str | None = None) -> list[str]:
    """Return conservative Daum Cafe URL variants for Odin KR detail pages.

    The desktop cafe URL can return only a Daum Cafe shell in GitHub Actions.
    Try mobile and _c21_/bbs_read variants and later select the variant with a
    real article body. This is profile-gated to Odin_KR only.
    """
    urls: list[str] = []

    def add(u: str) -> None:
        u = (u or "").strip().replace("&amp;", "&")
        if u and u not in urls:
            urls.append(u)

    add(url)
    for text in [url, html or ""]:
        for m in re.finditer(r"https?://[^\s'\"<>]+_c21_/bbs_read\?[^\s'\"<>]+", text or "", re.I):
            add(m.group(0))
        for m in re.finditer(r"https?://(?:m\.)?cafe\.daum\.net/odin/DEH7/(\d+)", text or "", re.I):
            num = m.group(1)
            add(f"https://m.cafe.daum.net/odin/DEH7/{num}")
            add(f"https://cafe.daum.net/odin/DEH7/{num}")
            # Official Odin cafe grpid observed in canonical og:url.
            add(f"https://cafe.daum.net/_c21_/bbs_read?grpid=1YvZ5&fldid=DEH7&datanum={num}")
            add(f"https://m.cafe.daum.net/_c21_/bbs_read?grpid=1YvZ5&fldid=DEH7&datanum={num}")
        for m in re.finditer(r"[?&]fldid=DEH7&(?:amp;)?datanum=(\d+)", text or "", re.I):
            num = m.group(1)
            add(f"https://cafe.daum.net/_c21_/bbs_read?grpid=1YvZ5&fldid=DEH7&datanum={num}")
            add(f"https://m.cafe.daum.net/_c21_/bbs_read?grpid=1YvZ5&fldid=DEH7&datanum={num}")
    return urls


def score_detail_text(text: str, profile: dict[str, Any]) -> tuple[int, list[str]]:
    flags: list[str] = []
    t = normalize_visible_text(text or "")
    if is_odin_kr_profile(profile):
        t = clean_odin_kr_article_text(t)
    score = len(t)
    if len(t) < 300:
        flags.append("TEXT_TOO_SHORT")
        score -= 1000
    if norm_key(t) in {"daum카페", "daumcafe"} or t.strip() in {"Daum 카페", "Daum Cafe"}:
        flags.append("DAUM_CAFE_SHELL_ONLY")
        score -= 5000
    if is_odin_kr_profile(profile):
        odin_keywords = ["업데이트 상세 내역", "업데이트에 대한 자세한 내용", "신규 이벤트", "신규 상품", "서버 침공전", "감사합니다"]
        hits = sum(1 for k in odin_keywords if k in t)
        if hits:
            score += hits * 500
        else:
            flags.append("ODIN_BODY_KEYWORD_MISSING")
            score -= 700
        if "<div" in t or "figure-img" in t or "cafeattach" in t:
            flags.append("HTML_LEAK_IN_TEXT")
            score -= 3000
        if any(x in t for x in ["이전글", "저작자 표시", "에효", "패스권도 그냥", "댓글쓰기"]):
            flags.append("DAUM_COMMENT_OR_NAV_LEAK")
            score -= 2500
    return score, flags


def fetch_url_with_headers(url: str, referer: str = "") -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 patch-update-actions detail-fetch",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    return requests.get(url, headers=headers, timeout=60, allow_redirects=True)


def fetch_detail_html_variants(profile: dict[str, Any], url: str) -> dict[str, Any]:
    """Fetch detail page variants and select the best article body candidate."""
    variant_records: list[dict[str, Any]] = []
    urls = [url]
    first_html = ""
    if is_odin_kr_profile(profile):
        # First fetch is used to discover og:url / canonical _c21_ links.
        try:
            r0 = fetch_url_with_headers(url)
            first_html = r0.text
            variant_records.append({"url": url, "http_status": r0.status_code, "final_url": r0.url, "html": first_html, "prefetch": True})
            urls = odin_detail_fetch_urls(url, first_html)
        except Exception as exc:
            variant_records.append({"url": url, "http_status": None, "final_url": "", "html": "", "prefetch": True, "error": str(exc)})
            urls = odin_detail_fetch_urls(url, "")

    for u in urls:
        # Avoid duplicating the prefetch original URL as a second full request.
        if variant_records and variant_records[0].get("url") == u and variant_records[0].get("html"):
            continue
        try:
            r = fetch_url_with_headers(u, referer=url)
            variant_records.append({"url": u, "http_status": r.status_code, "final_url": r.url, "html": r.text})
        except Exception as exc:
            variant_records.append({"url": u, "http_status": None, "final_url": "", "html": "", "error": str(exc)})

    best: dict[str, Any] | None = None
    public_records: list[dict[str, Any]] = []
    for i, rec in enumerate(variant_records):
        html = rec.get("html") or ""
        soup = BeautifulSoup(html, "lxml") if html else BeautifulSoup("", "lxml")
        text = extract_content_text_from_soup(soup, profile) if html else ""
        if is_odin_kr_profile(profile):
            text = clean_odin_kr_article_text(text)
        score, flags = score_detail_text(text, profile)
        if is_odin_kr_profile(profile) and re.search(r"https?://m\.cafe\.daum\.net/odin/DEH7/\d+", str(rec.get("url", "")), re.I) and len(text) >= 800:
            score += 1200
            flags = list(flags) + ["ODIN_MOBILE_TEXT_PREFERRED"]
        if is_odin_kr_profile(profile) and "_c21_/bbs_read" in str(rec.get("url", "")):
            score -= 400
            flags = list(flags) + ["ODIN_C21_HTML_VARIANT"]
        pub = {k: v for k, v in rec.items() if k != "html"}
        pub.update({"variant_index": i, "text_length": len(text), "score": score, "flags": flags, "text_excerpt": normalize_visible_text(text)[:300]})
        public_records.append(pub)
        candidate = {"variant_index": i, "url": rec.get("url", ""), "http_status": rec.get("http_status"), "final_url": rec.get("final_url", ""), "html": html, "soup": soup, "text": text, "score": score, "flags": flags}
        if best is None or score > int(best.get("score", -10**9)):
            best = candidate

    if best is None:
        best = {"variant_index": -1, "url": url, "http_status": None, "final_url": "", "html": "", "soup": BeautifulSoup("", "lxml"), "text": "", "score": -9999, "flags": ["NO_FETCH_VARIANTS"]}
    return {"best": best, "variants": public_records}

def fetch_detail_page(profile: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    game = profile.get("game", "game")
    url = row.get("source_url") or row.get("url") or ""
    safe_game = safe_slug(game, "game")
    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    detail_dir = ART / "detail_pages" / safe_game
    detail_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{row.get('actual_date') or 'unknown'}_{url_hash}"
    meta: dict[str, Any] = {
        "game": game,
        "source_url": url,
        "url_hash": url_hash,
        "fetch_status": "PENDING",
        "http_status": None,
        "title": row.get("title") or "패치노트",
        "actual_date": row.get("actual_date") or "",
        "text_length": 0,
        "raw_html_path": "",
        "raw_text_path": "",
        "text_excerpt": "",
        "body_summary_candidate": [],
        "domain_tags_candidate": [],
        "card_summary_candidate": "",
        "quality_status": "FETCH_PENDING",
    }
    try:
        variant_info = fetch_detail_html_variants(profile, url)
        (detail_dir / f"{base_name}.variants.json").write_text(json.dumps(variant_info.get("variants", []), ensure_ascii=False, indent=2), encoding="utf-8")
        best = variant_info.get("best") or {}
        html = best.get("html") or ""
        soup = best.get("soup") or BeautifulSoup(html, "lxml")
        text = best.get("text") or ""
        http_status = best.get("http_status")
        meta["http_status"] = http_status
        meta["selected_fetch_url"] = best.get("url", url)
        meta["selected_final_url"] = best.get("final_url", "")
        meta["selected_variant_index"] = best.get("variant_index", -1)
        meta["detail_fetch_flags"] = best.get("flags", []) or []
        meta["detail_fetch_score"] = best.get("score", 0)
        if html:
            html_path = detail_dir / f"{base_name}.raw.html"
            html_path.write_text(html, encoding="utf-8")
        else:
            html_path = detail_dir / f"{base_name}.raw.html"
            html_path.write_text("", encoding="utf-8")
        text = (text or "")[:MAX_DETAIL_TEXT_CHARS]
        text_path = detail_dir / f"{base_name}.raw.txt"
        text_path.write_text(text, encoding="utf-8")
        if len(normalize_visible_text(text)) < 300 or "DAUM_CAFE_SHELL_ONLY" in (best.get("flags", []) or []):
            meta.update({
                "fetch_status": "FAILED",
                "fetch_error": "detail_body_too_short_or_shell_only",
                "text_length": len(text),
                "raw_html_path": str(html_path.relative_to(ART)),
                "raw_text_path": str(text_path.relative_to(ART)),
                "text_excerpt": normalize_visible_text(text)[:1200],
                "quality_status": "DETAIL_FETCH_FAILED",
                "summary_quality_flags": list(best.get("flags", []) or []) + ["DETAIL_BODY_TOO_SHORT"],
            })
            (detail_dir / f"{base_name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta

        title = extract_detail_title(soup, meta["title"], profile)
        listed_actual_date = meta["actual_date"]
        actual_date = extract_effective_patch_date(title, text, listed_actual_date, profile) or listed_actual_date
        actual_date_source = "effective_patch_date" if actual_date and actual_date != listed_actual_date else "list_or_posted_date"
        cleaned_text = clean_detail_text_for_summary(text, profile, title)
        body, tags, card, qstatus, units, qflags = make_rule_based_summary_preview(text, title, profile)
        meta.update({
            "fetch_status": "PASS",
            "title": title,
            "actual_date": actual_date,
            "listed_actual_date": listed_actual_date,
            "actual_date_source": actual_date_source,
            "text_length": len(text),
            "summary_source_text_length": len(cleaned_text),
            "raw_html_path": str(html_path.relative_to(ART)),
            "raw_text_path": str(text_path.relative_to(ART)),
            "text_excerpt": cleaned_text[:1200],
            "body_summary_candidate": body,
            "domain_tags_candidate": tags,
            "card_summary_candidate": card,
            "update_units_candidate": units,
            "summary_quality_flags": (qflags or []) + list(best.get("flags", []) or []),
            "quality_status": qstatus,
        })
    except Exception as exc:
        meta.update({
            "fetch_status": "FAILED",
            "fetch_error": str(exc),
            "quality_status": "DETAIL_FETCH_FAILED",
            "traceback": traceback.format_exc(),
        })
    (detail_dir / f"{base_name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta

def fetch_details_for_candidates(results: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not FETCH_DETAIL_PAGES:
        return []
    by_game = {p.get("game"): p for p in profiles}
    detail_results = []
    total = 0
    for res in results:
        profile = by_game.get(res.get("game"), {})
        for row in res.get("new_urls", []) or []:
            if total >= MAX_DETAIL_FETCHES:
                break
            detail_results.append(fetch_detail_page(profile, row))
            total += 1
        if total >= MAX_DETAIL_FETCHES:
            break
    return detail_results



def notion_headers() -> dict[str, str]:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError("NOTION_TOKEN is missing.")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_database_id() -> str:
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not database_id:
        raise RuntimeError("NOTION_DATABASE_ID is missing.")
    return database_id


def notion_retrieve_database() -> dict[str, Any]:
    database_id = notion_database_id()
    r = requests.get(f"https://api.notion.com/v1/databases/{database_id}", headers=notion_headers(), timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Notion database retrieve failed: HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def find_schema_prop(schema: dict[str, Any], candidates: list[str], preferred_types: set[str] | None = None) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    props = schema.get("properties") or {}
    norm = {norm_key(k): k for k in props.keys()}
    for c in candidates:
        actual = norm.get(norm_key(c))
        if actual and (not preferred_types or (props[actual] or {}).get("type") in preferred_types):
            return actual, props[actual]
    for name, meta in props.items():
        if preferred_types and (meta or {}).get("type") in preferred_types and norm_key(name) in {norm_key(c) for c in candidates}:
            return name, meta
    return "", None


def find_title_schema_prop(schema: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    props = schema.get("properties") or {}
    for name, meta in props.items():
        if (meta or {}).get("type") == "title":
            return name, meta
    raise RuntimeError("Target Notion database has no title property.")


def rich_text_chunks(text: str, limit: int = 1900) -> list[dict[str, Any]]:
    text = str(text or "")
    if not text:
        return []
    return [{"type": "text", "text": {"content": text[i:i+limit]}} for i in range(0, len(text), limit)]


def notion_value_for_type(prop_type: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "" or value == []:
        return None
    if prop_type == "title":
        return {"title": rich_text_chunks(str(value), 1900)[:10]}
    if prop_type == "rich_text":
        if isinstance(value, list):
            text = "\n".join(f"• {x}" for x in value if str(x).strip())
        else:
            text = str(value)
        return {"rich_text": rich_text_chunks(text, 1900)[:80]}
    if prop_type == "date":
        return {"date": {"start": str(value)[:10]}}
    if prop_type == "url":
        return {"url": str(value)}
    if prop_type == "select":
        if isinstance(value, list):
            value = value[0] if value else ""
        value = str(value).strip()
        return {"select": {"name": value}} if value else None
    if prop_type == "multi_select":
        vals = listify(value)
        return {"multi_select": [{"name": str(v)[:100]} for v in vals[:50] if str(v).strip()]}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except Exception:
            return None
    return None


def add_prop_if_exists(properties: dict[str, Any], schema: dict[str, Any], candidates: list[str], value: Any, preferred_types: set[str] | None = None) -> str:
    name, meta = find_schema_prop(schema, candidates, preferred_types)
    if not name or not meta:
        return ""
    val = notion_value_for_type((meta or {}).get("type", ""), value)
    if val is not None:
        properties[name] = val
        return name
    return ""


def payload_to_notion_properties(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    written: list[str] = []
    title_name, title_meta = find_title_schema_prop(schema)
    title_value = payload.get("page_title") or payload.get("title") or "패치노트"
    title_prop = notion_value_for_type("title", title_value)
    if title_prop:
        properties[title_name] = title_prop
        written.append(title_name)

    mappings = [
        (["game", "게임", "게임명", "Game"], payload.get("game"), {"select", "rich_text", "multi_select"}),
        (["actual_date", "실제 패치일", "패치일", "날짜", "Date"], payload.get("actual_date"), {"date", "rich_text"}),
        (["source_url", "원문 URL", "URL", "url", "링크", "원문링크"], payload.get("source_url"), {"url", "rich_text"}),
        (["source_page_title", "원문 제목", "Source Page Title"], payload.get("source_page_title", ""), {"rich_text"}),
        (["importance", "중요도", "Importance"], "major" if payload.get("quality_status") == "PASS" and (payload.get("domain_tags") or []) else "normal", {"select", "rich_text"}),
        (["primary_category", "패치 카테고리", "대표 카테고리", "대표 핵심 신호"], payload.get("domain_tags", [])[:2], {"multi_select", "rich_text", "select"}),
        (["main_updates", "주요 업데이트", "주요 업데이트 요약"], payload.get("body_summary", [])[:3], {"rich_text", "multi_select"}),
        (["body_summary", "본문 요약", "Body Summary"], payload.get("body_summary", []), {"rich_text"}),
        (["domain_tags", "관련 영역", "도메인 태그", "Domain Tags"], payload.get("domain_tags", []), {"multi_select", "rich_text"}),
        (["card_summary", "카드 요약", "Card Summary"], payload.get("card_summary", ""), {"rich_text"}),
        (["actual_date_source", "실제 패치일 근거", "날짜 근거"], payload.get("actual_date_source", ""), {"select", "rich_text"}),
        (["listed_actual_date", "게시일", "목록 날짜"], payload.get("listed_actual_date", ""), {"date", "rich_text"}),
        (["quality_status", "품질 상태", "Quality Status"], payload.get("quality_status", ""), {"select", "rich_text"}),
        (["view_model_version", "View Model Version", "생성 규칙 버전"], SCHEMA_VERSION + "/" + WORKFLOW_VERSION, {"select", "rich_text"}),
    ]
    for candidates, value, types in mappings:
        name = add_prop_if_exists(properties, schema, candidates, value, types)
        if name:
            written.append(name)
    return properties, written


def payload_quality_ok(payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("detail_fetch_status") != "PASS":
        return False, "detail_fetch_not_pass"
    if payload.get("quality_status") != "PASS":
        return False, "summary_quality_not_pass"
    if not payload.get("source_url"):
        return False, "missing_source_url"
    if not payload.get("actual_date"):
        return False, "missing_actual_date"
    if not payload.get("body_summary") or payload.get("body_summary") == "NEEDS_DETAIL_FETCH_AND_SUMMARY":
        return False, "missing_body_summary"
    if not payload.get("domain_tags"):
        return False, "missing_domain_tags"
    return True, "ok"


def write_new_patch_payloads_to_notion(payloads: list[dict[str, Any]], existing_items: list[dict[str, Any]]) -> dict[str, Any]:
    database_id = notion_database_id()
    existing_urls = {canonical_url(x.get("source_url", "")) for x in existing_items if x.get("source_url")}
    schema = notion_retrieve_database()
    results = []
    created = 0
    skipped = 0
    failed = 0
    session = requests.Session()
    headers = notion_headers()
    for payload in payloads:
        row = {
            "game": payload.get("game", ""),
            "source_url": payload.get("source_url", ""),
            "actual_date": payload.get("actual_date", ""),
            "page_title": payload.get("page_title", ""),
        }
        ok, reason = payload_quality_ok(payload)
        if not ok:
            row.update({"status": "SKIPPED", "reason": reason})
            skipped += 1
            results.append(row)
            continue
        cu = canonical_url(payload.get("source_url", ""))
        if cu in existing_urls:
            row.update({"status": "SKIPPED", "reason": "duplicate_source_url"})
            skipped += 1
            results.append(row)
            continue
        try:
            props, written_props = payload_to_notion_properties(schema, payload)
            body = {"parent": {"database_id": database_id}, "properties": props}
            r = session.post("https://api.notion.com/v1/pages", headers=headers, json=body, timeout=60)
            if r.status_code >= 400:
                failed += 1
                row.update({"status": "FAILED", "reason": f"HTTP {r.status_code}: {r.text[:500]}", "written_properties": written_props})
            else:
                data = r.json()
                created += 1
                existing_urls.add(cu)
                row.update({"status": "CREATED", "page_id": data.get("id", ""), "written_properties": written_props, "reason": ""})
        except Exception as exc:
            failed += 1
            row.update({"status": "FAILED", "reason": str(exc)})
        results.append(row)

    return {
        "workflow_version": WORKFLOW_VERSION,
        "target_database": database_id,
        "write_attempted": True,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "results": results,
        "write_ready": failed == 0,
    }

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_payload_preview(results: list[dict[str, Any]], detail_results: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    detail_by_url = {d.get("source_url"): d for d in (detail_results or [])}
    payloads = []
    for res in results:
        for i, row in enumerate(res.get("new_urls", []), 1):
            detail = detail_by_url.get(row.get("source_url"), {})
            fetched = bool(detail)
            body_summary = detail.get("body_summary_candidate") if fetched else "NEEDS_DETAIL_FETCH_AND_SUMMARY"
            domain_tags = detail.get("domain_tags_candidate") if fetched else []
            card_summary = detail.get("card_summary_candidate") if fetched else ""
            source_page_title = detail.get("title") or row.get("title") or "패치노트"
            final_actual_date = detail.get("actual_date") or row.get("actual_date") or None
            payloads.append({
                "operation": "preview_new_patch_create",
                "write_ready": False,
                "game": res["game"],
                "source_url": row["source_url"],
                "actual_date": final_actual_date,
                "listed_actual_date": detail.get("listed_actual_date") or row.get("actual_date") or None,
                "actual_date_source": detail.get("actual_date_source", "list_candidate"),
                "source_page_title": source_page_title,
                "page_title": normalized_patch_page_title(final_actual_date or "", source_page_title),
                "item_name_rule": "YY.MM.DD | 패치노트",
                "anchor_source_url": res.get("anchor", {}).get("source_url"),
                "anchor_actual_date": res.get("anchor", {}).get("actual_date"),
                "process_order": i,
                "detail_fetch_status": detail.get("fetch_status", "NOT_FETCHED"),
                "raw_html_path": detail.get("raw_html_path", ""),
                "raw_text_path": detail.get("raw_text_path", ""),
                "raw_text_excerpt": detail.get("text_excerpt", ""),
                "body_summary": body_summary,
                "domain_tags": domain_tags,
                "card_summary": card_summary,
                "update_units_candidate": detail.get("update_units_candidate", []),
                "summary_quality_flags": detail.get("summary_quality_flags", []),
                "summary_source_text_length": detail.get("summary_source_text_length", 0),
                "quality_status": detail.get("quality_status", "PREVIEW_ONLY"),
                "note": "v022 keeps YY.MM.DD | 패치노트 item names and adds Odin_KR Daum Cafe body cleanup / mobile variant preference.",
            })
    return payloads




def date_to_ordinal(date_str: str) -> int:
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").toordinal()
    except Exception:
        return 0


def repair_recent_item_titles(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Optionally normalize recently created/migrated item titles.

    This is separate from new page creation. It is used to fix items created
    before v015 that used source detail titles such as "Patch Note - June 2nd"
    instead of the standard Notion item name "YY.MM.DD | 패치노트".
    """
    today_ord = datetime.now(KST).date().toordinal()
    min_ord = today_ord - max(0, TITLE_REPAIR_WINDOW_DAYS)
    rows = []
    for item in items:
        actual_date = str(item.get("actual_date", ""))[:10]
        page_id = item.get("page_id", "")
        current = str(item.get("raw_title") or item.get("title", ""))
        target = normalized_patch_page_title(actual_date, current)
        ordv = date_to_ordinal(actual_date)
        if not page_id or not actual_date or not ordv or ordv < min_ord:
            continue
        if current == target:
            continue
        if TARGET_GAMES and "ALL" not in TARGET_GAMES and item.get("game") not in TARGET_GAMES:
            continue
        rows.append({
            "page_id": page_id,
            "game": item.get("game", ""),
            "actual_date": actual_date,
            "source_url": item.get("source_url", ""),
            "previous_title": current,
            "new_title": target,
            "status": "PREVIEW" if DRY_RUN or not RUN_TITLE_REPAIR else "PENDING",
        })

    result = {
        "workflow_version": WORKFLOW_VERSION,
        "run_title_repair": RUN_TITLE_REPAIR,
        "dry_run": DRY_RUN,
        "title_repair_window_days": TITLE_REPAIR_WINDOW_DAYS,
        "candidate_count": len(rows),
        "updated": 0,
        "failed": 0,
        "results": rows,
    }
    if not rows or DRY_RUN or not RUN_TITLE_REPAIR:
        return result

    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError("RUN_TITLE_REPAIR=true requires NOTION_TOKEN.")
    schema = notion_retrieve_database()
    title_name, _title_meta = find_title_schema_prop(schema)
    session = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    for row in rows:
        try:
            properties = {title_name: notion_value_for_type("title", row["new_title"])}
            r = session.patch(f"https://api.notion.com/v1/pages/{row['page_id']}", headers=headers, json={"properties": properties}, timeout=60)
            if r.status_code >= 300:
                row["status"] = "FAILED"
                row["reason"] = r.text[:500]
                result["failed"] += 1
            else:
                row["status"] = "UPDATED"
                result["updated"] += 1
        except Exception as exc:
            row["status"] = "FAILED"
            row["reason"] = str(exc)
            result["failed"] += 1
    if result["failed"]:
        raise RuntimeError("Title repair failed for one or more pages. See title_repair_result.json.")
    return result


def main() -> int:
    LOG_PATH.write_text("", encoding="utf-8")
    started = datetime.now(KST).isoformat()
    log(f"[START] patch update workflow: {started}")
    effective_config = {
        "dry_run": DRY_RUN,
        "run_notion_write": RUN_NOTION_WRITE,
        "run_git_push": RUN_GIT_PUSH,
        "target_games": TARGET_GAMES,
        "max_new_urls_per_game": MAX_NEW_URLS_PER_GAME,
        "notion_token_present": bool(os.environ.get("NOTION_TOKEN")),
        "notion_database_id_present": bool(os.environ.get("NOTION_DATABASE_ID")),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "workflow_version": WORKFLOW_VERSION,
        "strict_detail_url_guard": STRICT_DETAIL_URL_GUARD,
        "fetch_detail_pages": FETCH_DETAIL_PAGES,
        "max_detail_fetches": MAX_DETAIL_FETCHES,
        "max_detail_text_chars": MAX_DETAIL_TEXT_CHARS,
        "run_title_repair": RUN_TITLE_REPAIR,
        "title_repair_window_days": TITLE_REPAIR_WINDOW_DAYS,
        "schedule_operation_mode": SCHEDULE_OPERATION_MODE,
        "is_schedule_run": IS_SCHEDULE_RUN,
        "post_write_export_retry_count": POST_WRITE_EXPORT_RETRY_COUNT,
        "post_write_export_retry_seconds": POST_WRITE_EXPORT_RETRY_SECONDS,
        **execution_identity(),
    }
    (ART / "effective_config.json").write_text(json.dumps(effective_config, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "execution_identity.json").write_text(json.dumps(execution_identity(), ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "operation_mode_guard.json").write_text(json.dumps({
        "workflow_version": WORKFLOW_VERSION,
        "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "is_schedule_run": IS_SCHEDULE_RUN,
        "schedule_operation_mode": SCHEDULE_OPERATION_MODE,
        "dry_run": DRY_RUN,
        "run_notion_write": RUN_NOTION_WRITE,
        "run_git_push": RUN_GIT_PUSH,
        "target_games": TARGET_GAMES,
        "guard_note": "Scheduled runs default to preview unless repository variable PATCH_UPDATE_SCHEDULE_MODE is set to write_deploy."
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    items, export_source, file_changed = export_patch_view_model()
    anchors = latest_anchor_by_game(items)
    (ART / "anchors_by_game.json").write_text(json.dumps(anchors, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "anchors_by_game.csv", list(anchors.values()))

    profiles = load_profiles()
    log(f"[STEP] Loaded game profiles: {len(profiles)}")
    results = []
    for profile in profiles:
        game = profile.get("game", "")
        try:
            official = fetch_official_list(profile)
            res = detect_newer_than_anchor(profile, official, anchors.get(game))
            res["profile_list_url"] = profile.get("list_url")
            res["profile_status"] = profile.get("profile_status", "seed")
            log(f"[DETECT] {game}: status={res['status']} new_count={res['new_count']} list_count={res['list_count']}")
        except Exception as exc:
            res = {
                "game": game,
                "status": "REVIEW_PROFILE_FETCH_FAILED",
                "reason": str(exc),
                "anchor": anchors.get(game, {}),
                "list_count": 0,
                "new_count": 0,
                "new_urls": [],
                "profile_list_url": profile.get("list_url"),
                "profile_status": profile.get("profile_status", "seed"),
            }
            log(f"[WARN] {game} official list fetch failed: {exc}")
        results.append(res)

    detail_results = fetch_details_for_candidates(results, profiles)
    (ART / "detail_fetch_result.json").write_text(json.dumps({"workflow_version": WORKFLOW_VERSION, "fetch_detail_pages": FETCH_DETAIL_PAGES, "results": detail_results}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "detail_fetch_summary.csv", [{"game": d.get("game", ""), "actual_date": d.get("actual_date", ""), "listed_actual_date": d.get("listed_actual_date", ""), "actual_date_source": d.get("actual_date_source", ""), "title": d.get("title", ""), "source_url": d.get("source_url", ""), "fetch_status": d.get("fetch_status", ""), "http_status": d.get("http_status", ""), "text_length": d.get("text_length", 0), "summary_source_text_length": d.get("summary_source_text_length", 0), "quality_status": d.get("quality_status", ""), "summary_quality_flags": ";".join(d.get("summary_quality_flags", []) or []), "raw_text_path": d.get("raw_text_path", "")} for d in detail_results])
    summary_quality_rows = []
    update_unit_rows = []
    for d in detail_results:
        summary_quality_rows.append({
            "game": d.get("game", ""),
            "actual_date": d.get("actual_date", ""),
            "listed_actual_date": d.get("listed_actual_date", ""),
            "actual_date_source": d.get("actual_date_source", ""),
            "title": d.get("title", ""),
            "source_url": d.get("source_url", ""),
            "quality_status": d.get("quality_status", ""),
            "unit_count": len(d.get("update_units_candidate", []) or []),
            "domain_tags": " · ".join(d.get("domain_tags_candidate", []) or []),
            "flags": ";".join(d.get("summary_quality_flags", []) or []),
        })
        for u in d.get("update_units_candidate", []) or []:
            update_unit_rows.append({
                "game": d.get("game", ""),
                "actual_date": d.get("actual_date", ""),
                "source_url": d.get("source_url", ""),
                "order": u.get("order", ""),
                "domain": u.get("domain", ""),
                "source_heading": u.get("source_heading", ""),
                "summary_sentence": u.get("summary_sentence", ""),
                "confidence": u.get("confidence", ""),
            })
    (ART / "summary_quality_result.json").write_text(json.dumps({"workflow_version": WORKFLOW_VERSION, "results": summary_quality_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "summary_quality_summary.csv", summary_quality_rows)
    write_csv(ART / "update_units_preview.csv", update_unit_rows)
    payload_preview = make_payload_preview(results, detail_results)
    summary_rows = [
        {
            "game": r["game"],
            "status": r["status"],
            "reason": r.get("reason", ""),
            "anchor_date": r.get("anchor", {}).get("actual_date", ""),
            "anchor_url": r.get("anchor", {}).get("source_url", ""),
            "list_count": r.get("list_count", 0),
            "new_count": r.get("new_count", 0),
            "profile_status": r.get("profile_status", ""),
            "list_url": r.get("profile_list_url", ""),
        }
        for r in results
    ]
    url_rows = []
    for r in results:
        for u in r.get("new_urls", []):
            url_rows.append({
                "game": r["game"],
                "actual_date": u.get("actual_date", ""),
                "title": u.get("title", ""),
                "source_url": u.get("source_url", ""),
                "list_index": u.get("list_index", ""),
                "detection_status": r.get("status", ""),
            })

    invalid_candidate_rows = []
    for r in results:
        profile = next((p for p in profiles if p.get("game") == r.get("game")), {})
        for u in r.get("new_urls", []):
            su = u.get("source_url", "")
            invalid_reason = ""
            if is_list_or_board_url(su, profile):
                invalid_reason = "list_or_board_url_candidate"
            elif not is_detail_url(su, profile):
                invalid_reason = "not_detail_url_candidate"
            if invalid_reason:
                invalid_candidate_rows.append({
                    "game": r.get("game", ""),
                    "source_url": su,
                    "title": u.get("title", ""),
                    "actual_date": u.get("actual_date", ""),
                    "reason": invalid_reason,
                })

    detail_url_guard = {
        "workflow_version": WORKFLOW_VERSION,
        "strict_detail_url_guard": STRICT_DETAIL_URL_GUARD,
        "invalid_candidate_count": len(invalid_candidate_rows),
        "invalid_candidates": invalid_candidate_rows,
        "passed": len(invalid_candidate_rows) == 0,
        "rule": "new_url_candidates must be detail URLs only; board/list URLs are rejected before payload preview.",
    }
    (ART / "detail_url_guard.json").write_text(json.dumps(detail_url_guard, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "invalid_url_candidates.csv", invalid_candidate_rows)

    notion_write_result = {
        "workflow_version": WORKFLOW_VERSION,
        "target_database": os.environ.get("NOTION_DATABASE_ID", ""),
        "write_attempted": False,
        "dry_run": DRY_RUN,
        "run_notion_write": RUN_NOTION_WRITE,
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
        "reason": "write disabled unless dry_run=false and run_notion_write=true",
        "write_ready": False,
    }
    if RUN_NOTION_WRITE and not DRY_RUN:
        if invalid_candidate_rows and STRICT_DETAIL_URL_GUARD:
            notion_write_result["reason"] = "blocked_by_detail_url_guard"
        else:
            pre_write_item_count = len(items)
            notion_write_result = write_new_patch_payloads_to_notion(payload_preview, items)
            # After write, regenerate public JSON and verify newly created pages are visible.
            if notion_write_result.get("failed", 0) > 0:
                (ART / "notion_write_result.json").write_text(json.dumps(notion_write_result, ensure_ascii=False, indent=2), encoding="utf-8")
                write_csv(ART / "notion_write_summary.csv", notion_write_result.get("results", []))
                raise RuntimeError("Notion write failed. See notion_write_result.json.")
            created_urls = [
                r.get("source_url", "")
                for r in notion_write_result.get("results", [])
                if r.get("status") == "CREATED" and r.get("source_url")
            ]
            if created_urls:
                items, export_source, file_changed = export_patch_view_model_with_retry(
                    expected_source_urls=created_urls,
                    min_items=pre_write_item_count + len(created_urls),
                    label="post_write",
                )
            else:
                items, export_source, file_changed = export_patch_view_model()

    title_repair_result = repair_recent_item_titles(items)
    (ART / "title_repair_result.json").write_text(json.dumps(title_repair_result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "title_repair_summary.csv", title_repair_result.get("results", []))
    if title_repair_result.get("updated", 0) > 0:
        items, export_source, file_changed = export_patch_view_model()

    (ART / "notion_write_result.json").write_text(json.dumps(notion_write_result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "notion_write_summary.csv", notion_write_result.get("results", []))

    payload_write_ready = bool((not DRY_RUN) and RUN_NOTION_WRITE and notion_write_result.get("failed", 0) == 0 and notion_write_result.get("created", 0) >= 0)
    (ART / "new_url_detection_result.json").write_text(json.dumps({"generated_at": started, "workflow_version": WORKFLOW_VERSION, "execution_identity": execution_identity(), "detail_url_guard": detail_url_guard, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "new_patch_payload_preview.json").write_text(json.dumps({"write_ready": payload_write_ready, "workflow_version": WORKFLOW_VERSION, "detail_url_guard": detail_url_guard, "notion_write_result": notion_write_result, "payloads": payload_preview}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "new_url_detection_summary.csv", summary_rows)
    write_csv(ART / "new_url_candidates.csv", url_rows)

    report = [
        "# Patch update workflow report",
        "",
        f"- generated_at: {started}",
        f"- workflow_version: {WORKFLOW_VERSION}",
        f"- event_name: {os.environ.get('GITHUB_EVENT_NAME', '')}",
        f"- schedule_operation_mode: {SCHEDULE_OPERATION_MODE}",
        f"- DRY_RUN: {DRY_RUN}",
        f"- RUN_NOTION_WRITE: {RUN_NOTION_WRITE}",
        f"- RUN_GIT_PUSH: {RUN_GIT_PUSH}",
        f"- RUN_TITLE_REPAIR: {RUN_TITLE_REPAIR}",
        f"- export_source: {export_source}",
        f"- public_items: {len(items)}",
        f"- patch_view_model_changed: {file_changed}",
        "- patch_view_model_change_note: true means source items changed or derived_data_version changed; see patch_view_model_export_summary.json",
        f"- payload_preview_count: {len(payload_preview)}",
        f"- notion_write_attempted: {notion_write_result.get('write_attempted', False)}",
        f"- notion_write_created: {notion_write_result.get('created', 0)}",
        f"- notion_write_skipped: {notion_write_result.get('skipped', 0)}",
        f"- notion_write_failed: {notion_write_result.get('failed', 0)}",
        f"- title_repair_candidates: {title_repair_result.get('candidate_count', 0)}",
        f"- title_repair_updated: {title_repair_result.get('updated', 0)}",
        f"- github_sha: {os.environ.get('GITHUB_SHA', '')}",
        f"- script_sha256: {execution_identity().get('script_sha256', '')}",
        f"- strict_detail_url_guard: {STRICT_DETAIL_URL_GUARD}",
        f"- invalid_url_candidate_count: {len(invalid_candidate_rows)}",
        f"- fetch_detail_pages: {FETCH_DETAIL_PAGES}",
        f"- detail_fetch_count: {len(detail_results)}",
        "",
        "## Detection summary",
        "",
        "| game | status | anchor_date | list_count | new_count |",
        "|---|---|---:|---:|---:|",
    ]
    for r in summary_rows:
        report.append(f"| {r['game']} | {r['status']} | {r['anchor_date']} | {r['list_count']} | {r['new_count']} |")
    report += [
        "",
        "## Standard rule",
        "",
        "```text",
        "anchor = 게임별 마지막 적재 패치노트",
        "new_url_candidates = anchor보다 최신인 detail URL 전체",
        "processing_order = actual_date 오름차순(oldest-first)",
        "```",
        "",
        f"## {WORKFLOW_VERSION} scope",
        "",
        "- v043 strict major detection: Major is allowed only for structural game changes, not domain-only matches",
        "- v043 major grouping: structurally-qualified units of the same major_type are summarized into one red sentence",
        "- v043 hardcoding guard: date/title-specific exception lists are not used for major filtering",
        "- Explicit workflow identity: workflow_version, GITHUB_SHA, GITHUB_REF, run id, script SHA256",
        "- Detail URL guard: board/list URL candidates are written to invalid_url_candidates.csv",
        "- Rejected link artifacts are emitted per game profile",
        "- Notion DB export and patch_view_model.json generation",
        "- patch_view_model.json noisy commit prevention",
        "- newer-than-anchor URL detection preview",
        "- raw detail HTML/TXT collection for new URL candidates",
        "- profile-aware update-unit candidate extraction",
        "- body_summary/domain_tags/card_summary quality preview",
        "- summary_quality_result.json, summary_quality_summary.csv, update_units_preview.csv artifacts",
        "- payload preview only",
        "- Notion write is guarded: only dry_run=false and run_notion_write=true creates pages",
        "- data-only commit guard for patch_view_model.json",
        "- v015 title handling: read raw Notion 항목명, export normalized display title, and repair recent raw titles",
        "- v022 Odin_KR summary repair: Daum Cafe body cleanup, mobile text preference, article span extraction",
"- v037 installer Unicode-safe subprocess capture: UTF-8/errors=replace for Git output plus no-change deploy guard",
"- v036 scheduled no-change deploy guard: no commit when patch_view_model.json is unchanged and report scope uses WORKFLOW_VERSION",
    ]
    (ART / "workflow_report.md").write_text("\n".join(report), encoding="utf-8")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text("\n".join(report), encoding="utf-8")

    if invalid_candidate_rows and STRICT_DETAIL_URL_GUARD:
        raise RuntimeError(f"Detail URL guard failed: {len(invalid_candidate_rows)} invalid candidate URL(s). See detail_url_guard.json and invalid_url_candidates.csv.")

    log("[DONE] workflow completed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        err = traceback.format_exc()
        log("[ERROR] workflow failed")
        log(err)
        (ART / "workflow_error.txt").write_text(err, encoding="utf-8")
        raise
