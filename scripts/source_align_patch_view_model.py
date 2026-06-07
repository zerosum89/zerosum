from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


DATA_PATH = Path("patch_view_model.json")
AUDIT_PATH = Path("source_alignment_audit.csv")

NEW = "\uc2e0\uaddc"
CLASS = "\ud074\ub798\uc2a4"
ADD = "\ucd94\uac00"


def load_items() -> tuple[Any, list[dict[str, Any]]]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, data
    return data, data.get("items", [])


def write_items(original: Any, items: list[dict[str, Any]]) -> None:
    if isinstance(original, list):
        DATA_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        original["items"] = items
        DATA_PATH.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")


def visible_text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


def fetch_text(session: requests.Session, url: str, cache: dict[str, tuple[int, str]]) -> tuple[int, str]:
    if not url:
        return 0, ""
    if url in cache:
        return cache[url]
    try:
        r = session.get(url, timeout=25)
        result = (r.status_code, visible_text(r.text))
    except Exception as exc:
        result = (0, f"FETCH_ERROR {exc}")
    cache[url] = result
    time.sleep(0.03)
    return result


def english_terms(text: str) -> list[str]:
    terms: list[str] = []
    for q in re.findall(r"[\u2018\u201c<\[]([^\u2019\u201d>\]]{3,80})[\u2019\u201d>\]]", text or ""):
        if re.search(r"[A-Za-z]", q):
            terms.append(q.strip())
    for m in re.findall(r"[A-Z][A-Za-z0-9]*(?:['\u2019.-]?[A-Za-z0-9]+)*(?:\s+[A-Z][A-Za-z0-9]*(?:['\u2019.-]?[A-Za-z0-9]+)*)*", text or ""):
        m = m.strip()
        if len(m) >= 4 and m not in {"MIR4", "MMORPG", "UI", "BM", "PvP", "PvE", "EXP", "ATK", "DEF", "CRIT", "UTC", "NPC", "PC", "ESC", "Book"}:
            terms.append(m)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def has_new_class_context(source_text: str, term: str = "") -> bool:
    lines = [x.strip() for x in (source_text or "").splitlines() if x.strip()]
    joined = "\n".join(lines).lower()
    if re.search(r"\bnew\s+class\b|\bnew\s+combat\s+class\b", joined, re.I):
        return True
    for line in lines:
        low = line.lower()
        if term and term.lower() not in low:
            continue
        if any(x in low for x in ["bug", "fixed", "appearance", "headpiece", "ranking"]):
            continue
        if re.search(r"class[^\n]{0,80}(will be added|added)|will be added[^\n]{0,80}class", low, re.I):
            return True
    return False


def has_add_context_for_term(source_text: str, term: str) -> bool:
    if not term:
        return False
    lines = [x.strip() for x in (source_text or "").splitlines() if x.strip()]
    term_low = term.lower()
    for idx, line in enumerate(lines):
        low = line.lower()
        if term_low not in low:
            continue
        window = " ".join(lines[max(0, idx - 2): min(len(lines), idx + 3)]).lower()
        if any(x in window for x in ["bug fix", "fixed an issue", "removed unused", "affected mounts", "appearance item per class"]):
            continue
        if re.search(r"\bnew\b|will be added|has been added|have been added|added\.?$|new content|new portal|new area|new region|new field", window, re.I):
            return True
    return False


def is_unsupported_summary_line(line: str, source_text: str) -> tuple[bool, str]:
    terms = english_terms(line)
    low_source = (source_text or "").lower()
    claim_new_class = (NEW in line and CLASS in line) or "new class" in line.lower()
    if claim_new_class:
        named = next((t for t in terms if t.lower() != "new class"), "")
        if not has_new_class_context(source_text, named):
            return True, "new_class_context_not_found"
    missing = [t for t in terms if t.lower() not in low_source]
    if missing and (NEW in line or ADD in line):
        return True, "add_claim_term_not_in_source:" + ";".join(missing[:4])
    if (NEW in line or ADD in line) and terms:
        unsupported_add_terms = [t for t in terms if t.lower() in low_source and not has_add_context_for_term(source_text, t)]
        if unsupported_add_terms:
            return True, "add_context_not_found:" + ";".join(unsupported_add_terms[:4])
    return False, ""


def compact_card_summary(lines: list[str]) -> str:
    domains: list[str] = []
    for line in lines:
        domain = line.split(":", 1)[0].strip() if ":" in line else ""
        if domain and domain not in domains:
            domains.append(domain)
    return " \u00b7 ".join(domains[:4])


def main() -> int:
    original, items = load_items()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 source-align-audit",
        "Accept-Language": "en-US,en;q=0.8,ko;q=0.6",
    })
    cache: dict[str, tuple[int, str]] = {}
    rows: list[dict[str, Any]] = []
    changed = 0
    removed = 0

    from scripts.patch_update_workflow import enrich_importance_display_fields

    for item in items:
        game = item.get("game_key") or item.get("game") or ""
        if game != "MIR4_Global":
            continue
        status, source_text = fetch_text(session, item.get("source_url") or item.get("url") or "", cache)
        old_lines = [str(x).strip() for x in item.get("body_summary") or [] if str(x).strip()]
        new_lines: list[str] = []
        removed_lines: list[str] = []
        reasons: list[str] = []
        for line in old_lines:
            drop, reason = is_unsupported_summary_line(line, source_text)
            if drop:
                removed_lines.append(line)
                reasons.append(reason)
            else:
                new_lines.append(line)
        if removed_lines:
            item["body_summary"] = new_lines
            item["main_updates"] = new_lines[:3]
            item["card_summary"] = compact_card_summary(new_lines)
            item["source_alignment_status"] = "repaired"
            item["source_alignment_removed_count"] = len(removed_lines)
            item["source_alignment_reasons"] = reasons
            enrich_importance_display_fields(item)
            changed += 1
            removed += len(removed_lines)
            rows.append({
                "game": game,
                "actual_date": item.get("actual_date", ""),
                "title": item.get("title", ""),
                "source_url": item.get("source_url") or item.get("url") or "",
                "http_status": status,
                "removed_count": len(removed_lines),
                "removed_summary": " | ".join(removed_lines),
                "reasons": " | ".join(reasons),
                "remaining_count": len(new_lines),
                "importance_decision": item.get("importance_decision", ""),
            })

    write_items(original, items)
    with AUDIT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["game", "actual_date", "title", "source_url", "http_status", "removed_count", "removed_summary", "reasons", "remaining_count", "importance_decision"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[source-align] MIR4_Global changed_items={changed} removed_lines={removed} fetched_urls={len(cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
