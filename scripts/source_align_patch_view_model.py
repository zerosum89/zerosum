from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from source_section_extractors_v2 import section_summary_preview


DATA_PATH = Path(os.environ.get("SOURCE_ALIGN_DATA_PATH", "patch_view_model.json"))
AUDIT_PATH = Path(os.environ.get("SOURCE_ALIGN_AUDIT_PATH", "source_alignment_audit.csv"))


def load_items() -> tuple[Any, list[dict[str, Any]]]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, data
    return data, data.get("items", [])


def write_items(original: Any, items: list[dict[str, Any]]) -> None:
    if isinstance(original, list):
        payload = json.dumps(items, ensure_ascii=False, indent=2)
    else:
        original["items"] = items
        payload = json.dumps(original, ensure_ascii=False, indent=2)
    # 유효성 검증 먼저
    test_parse = json.loads(payload)  # 파싱 실패 시 여기서 예외 발생
    del test_parse
    # OneDrive 동기화 간섭 방지: 로컬 Temp에 먼저 쓰고 복사
    import tempfile, shutil, os
    tmp_dir = Path(tempfile.gettempdir())
    tmp = tmp_dir / (DATA_PATH.stem + ".tmp_align")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    # 검증 후 최종 복사
    verify = json.loads(tmp.read_text(encoding="utf-8"))
    del verify
    shutil.copy2(str(tmp), str(DATA_PATH))
    tmp.unlink(missing_ok=True)
    print(f"[write_items] 저장 완료: {DATA_PATH} ({len(payload):,} chars)")


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "form"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def fetch_text(session: requests.Session, url: str, cache: dict[str, tuple[int, str]]) -> tuple[int, str]:
    if not url:
        return 0, ""
    if url in cache:
        return cache[url]
    try:
        r = session.get(url, timeout=30)
        result = (r.status_code, visible_text(r.text))
        if "cafe.daum.net/odin/" in url and "m.cafe.daum.net" not in url and len(result[1]) < 200:
            mobile_url = url.replace("https://cafe.daum.net/", "https://m.cafe.daum.net/")
            r = session.get(mobile_url, timeout=30)
            result = (r.status_code, visible_text(r.text))
    except Exception as exc:
        result = (0, f"FETCH_ERROR {exc}")
    cache[url] = result
    time.sleep(0.03)
    return result


def load_enricher():
    for candidate in [Path(__file__).resolve().parent, Path.cwd() / "scripts"]:
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        from patch_update_workflow import enrich_importance_display_fields
        return enrich_importance_display_fields
    except Exception:
        def passthrough(_: dict[str, Any]) -> dict[str, Any]:
            return _
        return passthrough


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None:
        return []
    return [str(value).strip()] if str(value).strip() else []


def target_games() -> set[str] | None:
    raw = os.environ.get("SOURCE_ALIGN_TARGET_GAMES", "ALL").strip()
    if not raw or raw.upper() == "ALL":
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def main() -> int:
    original, items = load_items()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 source-section-align",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    cache: dict[str, tuple[int, str]] = {}
    rows: list[dict[str, Any]] = []
    changed_by_game: Counter[str] = Counter()
    missing_by_game: Counter[str] = Counter()
    targets = target_games()
    enrich_importance_display_fields = load_enricher()

    for item in items:
        game = item.get("game_key") or item.get("game") or ""
        if targets is not None and game not in targets:
            continue
        status, source_text = fetch_text(session, item.get("source_url") or item.get("url") or "", cache)
        preview = section_summary_preview(game, source_text)
        new_body = listify(preview.get("body_summary"))
        old_body = listify(item.get("body_summary"))
        preview_status = str(preview.get("quality_status") or "")
        preview_flags = list(preview.get("flags", []) or [])
        if new_body and preview_status != "PASS":
            missing_by_game[game] += 1
            rows.append({
                "game": game,
                "actual_date": item.get("actual_date", ""),
                "title": item.get("title", ""),
                "source_url": item.get("source_url") or item.get("url") or "",
                "http_status": status,
                "status": "SECTION_REVIEW",
                "old_count": len(old_body),
                "new_count": len(new_body),
                "flags": ";".join(preview_flags),
                "old_body_summary": " | ".join(old_body),
                "new_body_summary": " | ".join(new_body),
            })
            continue
        if not new_body:
            if status == 200 and old_body:
                item["body_summary"] = []
                item["main_updates"] = []
                item["domain_tags"] = []
                item["primary_category"] = []
                item["card_summary"] = ""
                item["update_units"] = []
                item["source_section_extractor_status"] = "missing_cleared"
                item["source_section_extractor_rule"] = "source_section_extractor_v2"
                item["source_section_extractor_flags"] = preview_flags
                enrich_importance_display_fields(item)
                changed_by_game[game] += 1
                rows.append({
                    "game": game,
                    "actual_date": item.get("actual_date", ""),
                    "title": item.get("title", ""),
                    "source_url": item.get("source_url") or item.get("url") or "",
                    "http_status": status,
                    "status": "CLEARED_MISSING",
                    "old_count": len(old_body),
                    "new_count": 0,
                    "flags": ";".join(preview_flags),
                    "old_body_summary": " | ".join(old_body),
                    "new_body_summary": "",
                })
                continue
            missing_by_game[game] += 1
            rows.append({
                "game": game,
                "actual_date": item.get("actual_date", ""),
                "title": item.get("title", ""),
                "source_url": item.get("source_url") or item.get("url") or "",
                "http_status": status,
                "status": "SECTION_MISSING",
                "old_count": len(old_body),
                "new_count": 0,
                "flags": ";".join(preview_flags),
                "old_body_summary": " | ".join(old_body),
                "new_body_summary": "",
            })
            continue
        if old_body == new_body:
            continue

        item["body_summary"] = new_body
        item["main_updates"] = new_body[:3]
        item["domain_tags"] = listify(preview.get("domain_tags"))
        item["primary_category"] = listify(preview.get("domain_tags"))[:2]
        item["card_summary"] = str(preview.get("card_summary") or "")
        item["update_units"] = preview.get("units", [])
        item["source_section_extractor_status"] = "repaired"
        item["source_section_extractor_rule"] = "source_section_extractor_v2"
        item["source_section_extractor_flags"] = preview_flags
        enrich_importance_display_fields(item)
        changed_by_game[game] += 1
        rows.append({
            "game": game,
            "actual_date": item.get("actual_date", ""),
            "title": item.get("title", ""),
            "source_url": item.get("source_url") or item.get("url") or "",
            "http_status": status,
            "status": "REGENERATED",
            "old_count": len(old_body),
            "new_count": len(new_body),
            "flags": ";".join(preview_flags),
            "old_body_summary": " | ".join(old_body),
            "new_body_summary": " | ".join(new_body),
        })

    write_items(original, items)
    with AUDIT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "game", "actual_date", "title", "source_url", "http_status", "status",
            "old_count", "new_count", "flags", "old_body_summary", "new_body_summary",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[source-section-align] changed_by_game={dict(changed_by_game)}")
    print(f"[source-section-align] missing_by_game={dict(missing_by_game)}")
    print(f"[source-section-align] fetched_urls={len(cache)} audit_rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
