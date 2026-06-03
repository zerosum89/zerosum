#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
import hashlib
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
ROOT = Path.cwd()
ART = ROOT / "outputs" / "patch_workflow_artifacts"
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
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
SCHEMA_VERSION = "patch_view_model.v1"
WORKFLOW_VERSION = "github_actions_v007"


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
    title = str(pick(raw, ["title", "표시 제목", "정규화 제목", "패치 제목", "Name", "제목"], ""))
    if not title:
        date = actual_date.replace("-", ".")[2:] if actual_date else "--.--.--"
        title = f"{date} | 패치노트"

    return {
        "game": str(pick(raw, ["game", "게임", "게임명", "Game"], "")),
        "actual_date": actual_date,
        "title": title,
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

    current_items = existing_json_items()
    file_changed = stable_items(current_items) != stable_items(items)
    existing_path = ROOT / "patch_view_model.json"

    if not file_changed and existing_path.exists():
        log("[STEP] patch_view_model.json unchanged; existing file preserved to avoid noisy commits")
    else:
        output = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(KST).isoformat(),
            "source": source,
            "items": items,
        }
        existing_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[STEP] patch_view_model.json written: changed={file_changed}")

    (ART / "patch_view_model_export_summary.json").write_text(json.dumps({
        "source": source,
        "items": len(items),
        "file_changed": file_changed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return items, source, file_changed


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
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\b", text, re.I)
    if m:
        months = {name.lower(): i for i, name in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
        return f"{datetime.now(KST).year:04d}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        return f"{datetime.now(KST).year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


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
    seen = set()
    rejected = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        url = profile_canonical_url(urljoin(base, href), profile)
        if not url or url in seen:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        path = urlparse(url).path
        hay = f"{title} {url}"
        reject_reason = ""
        if url_patterns and not any(p.search(path) or p.search(url) for p in url_patterns):
            reject_reason = "url_include_mismatch"
        elif title_patterns and not any(p.search(hay) for p in title_patterns):
            reject_reason = "title_include_mismatch"
        elif exclude_patterns and any(p.search(hay) for p in exclude_patterns):
            reject_reason = "title_exclude_match"
        elif not is_detail_url(url, profile):
            reject_reason = "not_detail_url"
        if reject_reason:
            rejected.append({"url": url, "title": title, "reason": reject_reason})
            continue
        seen.add(url)
        out.append({"url": url, "canonical_url": url, "title": title, "actual_date": extract_date_from_text(hay)})
    (ART / f"rejected_links_{safe_game}.json").write_text(json.dumps(rejected[:200], ensure_ascii=False, indent=2), encoding="utf-8")
    return out[:MAX_LIST_ITEMS]


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
    selectors = profile.get("detail_title_selectors", []) or ["h1", ".title", ".tit", ".view-title", ".board-title"]
    for selector in selectors:
        try:
            node = soup.select_one(selector)
            if node:
                txt = " ".join(node.get_text(" ", strip=True).split())
                if txt and len(txt) >= 3:
                    return txt
        except Exception:
            continue
    if soup.title and soup.title.string:
        txt = " ".join(soup.title.string.split())
        if txt:
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


def make_rule_based_summary_preview(text: str, title: str) -> tuple[list[str], list[str], str, str]:
    # This is intentionally conservative. It creates a preview candidate, not final write-ready Korean copy.
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    candidates = []
    seen = set()
    bad_markers = ["facebook", "youtube", "discord", "google play", "app store", "copyright", "privacy", "terms", "고객센터", "로그인"]
    for line in lines:
        raw = " ".join(line.split())
        if len(raw) < 8 or len(raw) > 240:
            continue
        low = raw.lower()
        if any(m in low for m in bad_markers):
            continue
        domain = classify_domain(raw)
        if domain == "기타":
            continue
        key = norm_key(raw)[:80]
        if key in seen:
            continue
        seen.add(key)
        candidates.append((domain, raw))
        if len(candidates) >= 8:
            break
    if not candidates:
        fallback = truncate_sentence(title or "상세 원문 수집 완료", 120)
        return [f"원문 수집: {fallback} 원문이 수집되었으며 update-unit 요약 검토가 필요합니다."], ["원문 수집"], fallback, "RAW_COLLECTED_REVIEW"
    body = [f"{d}: {truncate_sentence(t, 170)}" for d, t in candidates[:6]]
    tags = []
    for d, _ in candidates:
        if d not in tags:
            tags.append(d)
    card = " · ".join(tags[:4])
    return body, tags, card, "RAW_COLLECTED_RULE_PREVIEW"


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
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 patch-update-actions detail-fetch"}, timeout=60)
        meta["http_status"] = r.status_code
        r.raise_for_status()
        html = r.text
        html_path = detail_dir / f"{base_name}.raw.html"
        html_path.write_text(html, encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        title = extract_detail_title(soup, meta["title"], profile)
        text = extract_content_text_from_soup(soup, profile)
        text = text[:MAX_DETAIL_TEXT_CHARS]
        text_path = detail_dir / f"{base_name}.raw.txt"
        text_path.write_text(text, encoding="utf-8")
        actual_date = extract_date_from_text("\n".join([title, text[:5000]])) or meta["actual_date"]
        body, tags, card, qstatus = make_rule_based_summary_preview(text, title)
        meta.update({
            "fetch_status": "PASS",
            "title": title,
            "actual_date": actual_date,
            "text_length": len(text),
            "raw_html_path": str(html_path.relative_to(ART)),
            "raw_text_path": str(text_path.relative_to(ART)),
            "text_excerpt": text[:1200],
            "body_summary_candidate": body,
            "domain_tags_candidate": tags,
            "card_summary_candidate": card,
            "quality_status": qstatus,
        })
    except Exception as exc:
        meta.update({
            "fetch_status": "FAILED",
            "fetch_error": str(exc),
            "quality_status": "DETAIL_FETCH_FAILED",
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
            payloads.append({
                "operation": "preview_new_patch_create",
                "write_ready": False,
                "game": res["game"],
                "source_url": row["source_url"],
                "actual_date": detail.get("actual_date") or row.get("actual_date") or None,
                "page_title": detail.get("title") or row.get("title") or "패치노트",
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
                "quality_status": detail.get("quality_status", "PREVIEW_ONLY"),
                "note": "v007 generates raw detail collection and rule-based summary candidates only. Notion write remains disabled.",
            })
    return payloads


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
        **execution_identity(),
    }
    (ART / "effective_config.json").write_text(json.dumps(effective_config, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "execution_identity.json").write_text(json.dumps(execution_identity(), ensure_ascii=False, indent=2), encoding="utf-8")

    if RUN_NOTION_WRITE:
        raise RuntimeError("RUN_NOTION_WRITE=true is not supported in v007. Use detection/detail-fetch/export preview only.")

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
    write_csv(ART / "detail_fetch_summary.csv", [{"game": d.get("game", ""), "actual_date": d.get("actual_date", ""), "title": d.get("title", ""), "source_url": d.get("source_url", ""), "fetch_status": d.get("fetch_status", ""), "http_status": d.get("http_status", ""), "text_length": d.get("text_length", 0), "quality_status": d.get("quality_status", ""), "raw_text_path": d.get("raw_text_path", "")} for d in detail_results])
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

    (ART / "new_url_detection_result.json").write_text(json.dumps({"generated_at": started, "workflow_version": WORKFLOW_VERSION, "execution_identity": execution_identity(), "detail_url_guard": detail_url_guard, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "new_patch_payload_preview.json").write_text(json.dumps({"write_ready": False, "workflow_version": WORKFLOW_VERSION, "detail_url_guard": detail_url_guard, "payloads": payload_preview}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(ART / "new_url_detection_summary.csv", summary_rows)
    write_csv(ART / "new_url_candidates.csv", url_rows)

    report = [
        "# Patch update workflow report",
        "",
        f"- generated_at: {started}",
        f"- workflow_version: {WORKFLOW_VERSION}",
        f"- DRY_RUN: {DRY_RUN}",
        f"- RUN_NOTION_WRITE: {RUN_NOTION_WRITE}",
        f"- RUN_GIT_PUSH: {RUN_GIT_PUSH}",
        f"- export_source: {export_source}",
        f"- public_items: {len(items)}",
        f"- patch_view_model_changed: {file_changed}",
        f"- payload_preview_count: {len(payload_preview)}",
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
        "## v007 scope",
        "",
        "- Explicit workflow identity: workflow_version, GITHUB_SHA, GITHUB_REF, run id, script SHA256",
        "- Detail URL guard: board/list URL candidates are written to invalid_url_candidates.csv",
        "- Rejected link artifacts are emitted per game profile",
        "- Notion DB export and patch_view_model.json generation",
        "- patch_view_model.json noisy commit prevention",
        "- newer-than-anchor URL detection preview",
        "- raw detail HTML/TXT collection for new URL candidates",
        "- rule-based body_summary/domain_tags/card_summary preview candidates",
        "- payload preview only",
        "- Notion write intentionally disabled",
        "- data-only commit guard for patch_view_model.json",
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
