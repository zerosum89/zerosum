from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


DATA_PATH = Path(os.environ.get("SOURCE_ALIGN_DATA_PATH", "patch_view_model.json"))
AUDIT_PATH = Path(os.environ.get("SOURCE_ALIGN_AUDIT_PATH", "source_alignment_audit.csv"))

NEW = "\uc2e0\uaddc"
CLASS = "\ud074\ub798\uc2a4"
ADD = "\ucd94\uac00"
JOB = "\uc9c1\uc5c5"
OPEN = "\uc624\ud508"

GENERIC_TERMS = {
    "MIR4", "MMORPG", "UI", "BM", "PvP", "PvE", "EXP", "ATK", "DEF", "CRIT", "UTC", "NPC", "PC", "ESC",
    "Book", "Event", "Update", "Patch", "Class", "New", "Item", "Season", "Server", "World", "Field",
    "\ud328\uce58\ub178\ud2b8", "\uc5c5\ub370\uc774\ud2b8", "\uc2e0\uaddc", "\ucd94\uac00", "\uc774\ubca4\ud2b8", "\ubcf4\uc0c1",
    "\uc0c1\uc810", "\uc11c\ubc84", "\uc6d4\ub4dc", "\ud544\ub4dc", "\ucf58\ud150\uce20", "\uc544\uc774\ud15c", "\uc2dc\uc98c",
}

EN_STOPWORDS = {"of", "the", "and", "in", "on", "for", "with", "to", "a", "an", "system"}


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


def normalize_for_match(text: str) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", (text or "").lower())


def term_in_source(term: str, source_text: str, compact_source: str) -> bool:
    key = normalize_for_match(term)
    if not key:
        return False
    if term.lower() in (source_text or "").lower() or key in compact_source:
        return True
    if re.search(r"[A-Za-z]", term):
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", term) if t.lower() not in EN_STOPWORDS]
        if len(tokens) >= 2 and all(normalize_for_match(t) in compact_source for t in tokens):
            return True
    return False


def summary_terms(text: str) -> list[str]:
    terms: list[str] = []
    for q in re.findall(r"[\u2018\u201c<\[]([^\u2019\u201d>\]]{3,80})[\u2019\u201d>\]]", text or ""):
        q = q.strip()
        if q and q not in GENERIC_TERMS:
            terms.append(q)
    for m in re.findall(r"[A-Z][A-Za-z0-9]*(?:['\u2019.-]?[A-Za-z0-9]+)*(?:\s+[A-Z][A-Za-z0-9]*(?:['\u2019.-]?[A-Za-z0-9]+)*)*", text or ""):
        m = m.strip()
        if len(m) >= 4 and m not in GENERIC_TERMS:
            terms.append(m)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = normalize_for_match(term)
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def has_new_class_context(source_text: str, term: str = "") -> bool:
    lines = [x.strip() for x in (source_text or "").splitlines() if x.strip()]
    joined = "\n".join(lines).lower()
    joined_compact = normalize_for_match(source_text)
    if re.search(r"\bnew\s+class\b|\bnew\s+combat\s+class\b", joined, re.I):
        return True
    if ("\uc2e0\uaddc\ud074\ub798\uc2a4" in joined_compact or "\uc2e0\uaddc\uc9c1\uc5c5" in joined_compact
            or "\ud074\ub798\uc2a4\ucd94\uac00" in joined_compact or "\uc9c1\uc5c5\ucd94\uac00" in joined_compact):
        return True
    for line in lines:
        low = line.lower()
        compact = normalize_for_match(line)
        if term and normalize_for_match(term) not in compact:
            continue
        if any(x in low for x in ["bug", "fixed", "appearance", "headpiece", "ranking"]):
            continue
        if any(x in compact for x in ["\uc624\ub958\uc218\uc815", "\uc218\uc815", "\uc0ad\uc81c", "\uc81c\uac70", "\uc885\ub8cc", "\ub7ad\ud0b9"]):
            continue
        if re.search(r"class[^\n]{0,80}(will be added|added)|will be added[^\n]{0,80}class", low, re.I):
            return True
        if (CLASS in line or JOB in line) and (NEW in line or ADD in line):
            return True
    return False


def has_add_context_for_term(source_text: str, term: str) -> bool:
    if not term:
        return False
    lines = [x.strip() for x in (source_text or "").splitlines() if x.strip()]
    term_key = normalize_for_match(term)
    for idx, line in enumerate(lines):
        low = line.lower()
        compact = normalize_for_match(line)
        if term_key not in compact:
            continue
        window = " ".join(lines[max(0, idx - 2): min(len(lines), idx + 3)]).lower()
        window_compact = normalize_for_match(window)
        if any(x in window for x in ["bug fix", "fixed an issue", "removed unused", "affected mounts", "appearance item per class"]):
            continue
        if any(x in window_compact for x in ["\uc624\ub958\uc218\uc815", "\uc0ad\uc81c", "\uc885\ub8cc"]):
            continue
        if re.search(r"\bnew\b|will be added|has been added|have been added|added\.?$|new content|new portal|new area|new region|new field|starts?|begins?|available|will be held|event", window, re.I):
            return True
        if any(x in window_compact for x in [NEW, ADD, "\uc0c8\ub85c\uc6b4", "\ud655\uc7a5", "\uacf5\uac1c", "\uc801\uc6a9", "\uc9c4\ud589", "\uac1c\ucd5c", "\uc2dc\uc791"]):
            return True
    return False


def line_body(line: str) -> str:
    return line.split(":", 1)[1].strip() if ":" in line else line


def line_domain(line: str) -> str:
    return line.split(":", 1)[0].strip() if ":" in line else ""


def body_claims_new_class(body: str) -> bool:
    compact = normalize_for_match(body)
    if "\uc804\ud074\ub798\uc2a4" in compact:
        return False
    return bool(
        re.search(r"(?:\uc2e0\uaddc|\uc0c8\ub85c\uc6b4)\s*(?:\ud074\ub798\uc2a4|\uc9c1\uc5c5)", body)
        or "new class" in body.lower()
    )


def normalize_summary_line(line: str) -> tuple[str, str]:
    domain = line_domain(line)
    body = line_body(line)
    if domain == "\uc2e0\uaddc \ud074\ub798\uc2a4" and not body_claims_new_class(body):
        return f"\ud074\ub798\uc2a4/\uc2a4\ud0ac: {body}", "retag_new_class_domain"
    return line, ""


def is_unsupported_summary_line(line: str, source_text: str, status: int, game: str) -> tuple[bool, str]:
    if status < 200 or status >= 400 or len(source_text or "") < 200:
        return False, "source_fetch_unavailable"
    body = line_body(line)
    terms = summary_terms(body)
    compact_source = normalize_for_match(source_text)
    claim_new_class = body_claims_new_class(body)
    claim_add = NEW in body or ADD in body or "new " in body.lower() or "added" in body.lower()
    if claim_new_class:
        named = next((t for t in terms if t.lower() != "new class"), "")
        if not has_new_class_context(source_text, named):
            return True, "new_class_context_not_found"
    missing = [t for t in terms if not term_in_source(t, source_text, compact_source)]
    if missing and claim_add:
        return True, "add_claim_term_not_in_source:" + ";".join(missing[:4])
    if claim_add and terms and game == "MIR4_Global":
        unsupported_add_terms = [t for t in terms if term_in_source(t, source_text, compact_source) and not has_add_context_for_term(source_text, t)]
        if unsupported_add_terms:
            return True, "add_context_not_found:" + ";".join(unsupported_add_terms[:4])
    return False, ""


def compact_card_summary(lines: list[str]) -> str:
    domains = summary_domains(lines)
    return " \u00b7 ".join(domains[:4])


def summary_domains(lines: list[str]) -> list[str]:
    domains: list[str] = []
    for line in lines:
        domain = line.split(":", 1)[0].strip() if ":" in line else ""
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def target_games() -> set[str] | None:
    raw = os.environ.get("SOURCE_ALIGN_TARGET_GAMES", "ALL").strip()
    if not raw or raw.upper() == "ALL":
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def load_enricher():
    for candidate in [Path(__file__).resolve().parent, Path.cwd() / "scripts", Path.cwd() / "zerosum_clean_check" / "scripts"]:
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        from patch_update_workflow import enrich_importance_display_fields
        return enrich_importance_display_fields
    except Exception:
        def passthrough(_: dict[str, Any]) -> None:
            return None
        return passthrough


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
    rewritten = 0
    changed_by_game: Counter[str] = Counter()
    removed_by_game: Counter[str] = Counter()
    rewritten_by_game: Counter[str] = Counter()
    targets = target_games()

    enrich_importance_display_fields = load_enricher()

    for item in items:
        game = item.get("game_key") or item.get("game") or ""
        if targets is not None and game not in targets:
            continue
        status, source_text = fetch_text(session, item.get("source_url") or item.get("url") or "", cache)
        old_lines = [str(x).strip() for x in item.get("body_summary") or [] if str(x).strip()]
        new_lines: list[str] = []
        removed_lines: list[str] = []
        reasons: list[str] = []
        rewrite_reasons: list[str] = []
        for line in old_lines:
            normalized_line, rewrite_reason = normalize_summary_line(line)
            drop, reason = is_unsupported_summary_line(normalized_line, source_text, status, game)
            if drop:
                removed_lines.append(normalized_line)
                reasons.append(reason)
            else:
                new_lines.append(normalized_line)
                if rewrite_reason:
                    rewrite_reasons.append(rewrite_reason)
        if removed_lines or rewrite_reasons:
            domains = summary_domains(new_lines)
            item["body_summary"] = new_lines
            item["main_updates"] = new_lines[:3]
            item["domain_tags"] = domains
            item["primary_category"] = domains[:2]
            item["card_summary"] = " \u00b7 ".join(domains[:4])
            item["source_alignment_status"] = "repaired"
            item["source_alignment_removed_count"] = len(removed_lines)
            item["source_alignment_reasons"] = reasons
            if rewrite_reasons:
                item["source_alignment_rewrite_count"] = len(rewrite_reasons)
                item["source_alignment_rewrite_reasons"] = rewrite_reasons
            enrich_importance_display_fields(item)
            changed += 1
            removed += len(removed_lines)
            rewritten += len(rewrite_reasons)
            changed_by_game[game] += 1
            removed_by_game[game] += len(removed_lines)
            rewritten_by_game[game] += len(rewrite_reasons)
            rows.append({
                "game": game,
                "actual_date": item.get("actual_date", ""),
                "title": item.get("title", ""),
                "source_url": item.get("source_url") or item.get("url") or "",
                "http_status": status,
                "removed_count": len(removed_lines),
                "removed_summary": " | ".join(removed_lines),
                "reasons": " | ".join(reasons),
                "rewrite_count": len(rewrite_reasons),
                "rewrite_reasons": " | ".join(rewrite_reasons),
                "remaining_count": len(new_lines),
                "importance_decision": item.get("importance_decision", ""),
            })

    write_items(original, items)
    with AUDIT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["game", "actual_date", "title", "source_url", "http_status", "removed_count", "removed_summary", "reasons", "rewrite_count", "rewrite_reasons", "remaining_count", "importance_decision"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[source-align] changed_items={changed} removed_lines={removed} rewritten_lines={rewritten} fetched_urls={len(cache)}")
    print(f"[source-align] changed_by_game={dict(changed_by_game)}")
    print(f"[source-align] removed_by_game={dict(removed_by_game)}")
    print(f"[source-align] rewritten_by_game={dict(rewritten_by_game)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
