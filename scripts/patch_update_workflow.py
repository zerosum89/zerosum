#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
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
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
SCHEMA_VERSION = "patch_view_model.v1"
WORKFLOW_VERSION = "github_actions_v003"


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
    return ""


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
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        url = canonical_url(urljoin(base, href))
        if not url or url in seen:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        path = urlparse(url).path
        hay = f"{title} {url}"
        if url_patterns and not any(p.search(path) or p.search(url) for p in url_patterns):
            continue
        if title_patterns and not any(p.search(hay) for p in title_patterns):
            continue
        if exclude_patterns and any(p.search(hay) for p in exclude_patterns):
            continue
        seen.add(url)
        out.append({"url": url, "canonical_url": url, "title": title, "actual_date": extract_date_from_text(hay)})
    return out[:MAX_LIST_ITEMS]


def detect_newer_than_anchor(profile: dict[str, Any], official_list: list[dict[str, Any]], anchor: dict[str, Any] | None) -> dict[str, Any]:
    game = profile.get("game", "")
    order = profile.get("list_order", "newest_first")
    anchor_c = canonical_url((anchor or {}).get("source_url", ""))
    rows = []
    seen = set()
    for i, x in enumerate(official_list):
        c = canonical_url(x.get("canonical_url") or x.get("url") or "")
        if not c or c in seen:
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
        "list_count": len(rows),
        "new_count": len(candidates),
        "new_urls": candidates,
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


def make_payload_preview(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads = []
    for res in results:
        for i, row in enumerate(res.get("new_urls", []), 1):
            payloads.append({
                "operation": "preview_new_patch_create",
                "write_ready": False,
                "game": res["game"],
                "source_url": row["source_url"],
                "actual_date": row.get("actual_date") or None,
                "page_title": row.get("title") or "패치노트",
                "anchor_source_url": res.get("anchor", {}).get("source_url"),
                "anchor_actual_date": res.get("anchor", {}).get("actual_date"),
                "process_order": i,
                "body_summary": "NEEDS_DETAIL_FETCH_AND_SUMMARY",
                "domain_tags": [],
                "card_summary": "",
                "quality_status": "PREVIEW_ONLY",
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
    }
    (ART / "effective_config.json").write_text(json.dumps(effective_config, ensure_ascii=False, indent=2), encoding="utf-8")

    if RUN_NOTION_WRITE:
        raise RuntimeError("RUN_NOTION_WRITE=true is not supported in v003. Use detection/export preview only.")

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

    payload_preview = make_payload_preview(results)
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

    (ART / "new_url_detection_result.json").write_text(json.dumps({"generated_at": started, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "new_patch_payload_preview.json").write_text(json.dumps({"write_ready": False, "payloads": payload_preview}, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "new_url_candidates = anchor보다 최신인 URL 전체",
        "processing_order = actual_date 오름차순(oldest-first)",
        "```",
        "",
        "## v003 scope",
        "",
        "- Notion DB export and patch_view_model.json generation",
        "- patch_view_model.json noisy commit prevention",
        "- newer-than-anchor URL detection preview",
        "- payload preview only",
        "- Notion write intentionally disabled",
        "- data-only commit guard for patch_view_model.json",
    ]
    (ART / "workflow_report.md").write_text("\n".join(report), encoding="utf-8")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text("\n".join(report), encoding="utf-8")

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
