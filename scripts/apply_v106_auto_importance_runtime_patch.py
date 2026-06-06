from __future__ import annotations

import re
from pathlib import Path


PATCH_SCRIPT = Path("scripts/patch_update_workflow.py")
GATE_SCRIPT = Path("scripts/policy_gate_v093.py")

MAJOR_REASON = (
    "body_summary \uc790\ub3d9 \uaddc\uce59\uc774 \uad6c\uc870\uc801 \uc8fc\uc694 "
    "\uc5c5\ub370\uc774\ud2b8 \ubb38\uc7a5\uc744 \uac10\uc9c0\ud588\uc2b5\ub2c8\ub2e4."
)
NORMAL_REASON = (
    "body_summary \uc790\ub3d9 \uaddc\uce59\uc774 \uad6c\uc870\uc801 \uc8fc\uc694 "
    "\uc5c5\ub370\uc774\ud2b8 \ubb38\uc7a5\uc744 \uac10\uc9c0\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4."
)


def patch_workflow(text: str) -> str:
    text = text.replace(
        'DISPLAY_DATA_VERSION = "patch_view_model.v087_semantic_fields_from_notion"',
        'DISPLAY_DATA_VERSION = "patch_view_model.v106_auto_importance_decision"',
    )
    text = text.replace(
        'MAJOR_POLICY_VERSION = "major_policy_v087_semantic_fields_from_notion"',
        'MAJOR_POLICY_VERSION = "major_policy_v106_auto_from_body_summary"',
    )

    enrich_pattern = re.compile(
        r"def enrich_importance_display_fields\(item: dict\[str, Any\]\) -> dict\[str, Any\]:\n"
        r"[\s\S]*?\n(?=def normalize_item_from_notion\()"
    )
    enrich_replacement = f'''def enrich_importance_display_fields(item: dict[str, Any]) -> dict[str, Any]:
    # v106: body_summary-derived candidates are the source of truth.
    body_summary = listify(item.get("body_summary", []))
    auto_candidates = derive_highlight_sentence_candidates(body_summary)
    decision = "major" if auto_candidates else "normal"
    candidates = auto_candidates if decision == "major" else []

    suggestion_reasons = sorted({{
        str(c.get("highlight_reason", ""))
        for c in auto_candidates
        if c.get("highlight_reason")
    }})
    confidence = max([float(c.get("confidence", 0.0) or 0.0) for c in auto_candidates] or [0.76])

    stored_reason = str(item.get("importance_reason") or "").strip()
    if stored_reason and decision == "major":
        importance_reason = stored_reason
    elif decision == "major":
        importance_reason = {MAJOR_REASON!r}
    else:
        importance_reason = {NORMAL_REASON!r}

    item["highlight_sentence_candidates"] = candidates
    item["importance_suggestion"] = decision
    item["importance_suggestion_reason"] = suggestion_reasons
    item["importance_suggestion_confidence"] = confidence
    item["importance_decision"] = decision
    item["importance_decision_source"] = "auto_rule"
    item["importance_reason"] = importance_reason
    item["importance_review_status"] = "pass"
    item["display_highlight_count"] = len(candidates) if decision == "major" else 0
    item["quality_gate_status"] = "pass"

    old_key_specs = [
        ["derived", "major", "candidate", "groups"],
        ["derived", "major", "candidate", "count"],
        ["derived", "importance"],
        ["display", "importance"],
        ["importance", "source"],
        ["suppressed", "derived", "major", "candidate"],
        ["major", "without", "highlight", "candidate"],
        ["major", "summary", "groups"],
        ["major", "group", "count"],
        ["major", "summary", "indices"],
    ]
    for parts in old_key_specs:
        item.pop("_".join(parts), None)
    return item

'''
    text, count = enrich_pattern.subn(enrich_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("failed to patch enrich_importance_display_fields")

    helper = '''def highlight_candidates_to_notion_lines(candidates: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for c in candidates or []:
        if isinstance(c, dict):
            text = str(c.get("sentence") or c.get("text") or c.get("source_line") or "").strip()
            reason = str(c.get("highlight_reason") or "").strip()
            if text and reason:
                lines.append(f"{text} [{reason}]")
            elif text:
                lines.append(text)
        elif str(c).strip():
            lines.append(str(c).strip())
    return lines


'''
    if "def highlight_candidates_to_notion_lines(" not in text:
        text = text.replace(
            "def payload_to_notion_properties(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:\n",
            helper + "def payload_to_notion_properties(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:\n",
            1,
        )

    insert = f'''    auto_body_summary = listify(payload.get("body_summary", []))
    auto_highlight_candidates = derive_highlight_sentence_candidates(auto_body_summary)
    auto_importance = "major" if auto_highlight_candidates else "normal"
    auto_importance_reason = {MAJOR_REASON!r} if auto_importance == "major" else {NORMAL_REASON!r}
    auto_highlight_lines = highlight_candidates_to_notion_lines(auto_highlight_candidates)

'''
    if "auto_highlight_candidates = derive_highlight_sentence_candidates(auto_body_summary)" not in text:
        text = text.replace("    mappings = [\n", insert + "    mappings = [\n", 1)

    text = re.sub(
        r'(\(\["importance"[^\n]*?, )"major" if payload\.get\("quality_status"\) == "PASS" and \(payload\.get\("domain_tags"\) or \[\]\) else "normal"(, \{"select", "rich_text"\}\),)',
        r"\1auto_importance\2",
        text,
        count=1,
    )

    highlight_mapping = (
        '        (["highlight_sentence_candidates", "\\uc8fc\\uc694 \\ubb38\\uc7a5 \\ud6c4\\ubcf4", "\\uac15\\uc870 \\ubb38\\uc7a5 \\ud6c4\\ubcf4"], auto_highlight_lines, {"rich_text"}),\n'
        '        (["importance_reason", "\\uc911\\uc694\\ub3c4 \\ud310\\ub2e8 \\uadfc\\uac70", "\\uc8fc\\uc694 \\uc5ec\\ubd80 \\ud310\\ub2e8 \\uadfc\\uac70"], auto_importance_reason, {"rich_text"}),\n'
    )
    if '["highlight_sentence_candidates",' not in text:
        text = re.sub(
            r'(^\s*\(\["quality_status"[^\n]*\n)',
            highlight_mapping + r"\1",
            text,
            count=1,
            flags=re.MULTILINE,
        )

    text = text.replace(
        "- v060/v069 display rule: importance_decision controls major badge and highlight_sentence_candidates controls body-summary emphasis",
        "- v106 display rule: body_summary-derived highlight_sentence_candidates control importance_decision and body-summary emphasis",
    )
    return text


def patch_gate(text: str) -> str:
    text = text.replace(
        "- highlight_sentence_candidates are display candidates only.\n- importance_suggestion is an automatic suggestion only.\n- importance_decision is the final display/write decision.",
        "- highlight_sentence_candidates are automatic body_summary-derived candidates.\n- importance_suggestion mirrors the automatic decision.\n- importance_decision is the final display/write decision from auto_rule.",
    )
    text = text.replace(
        '        if decision == "major" and not candidates:\n            row_warnings.append("major decision has no highlight candidates")',
        '        if decision == "major" and not candidates:\n            row_errors.append("major decision has no highlight candidates")\n        if decision == "major" and not str(item.get("importance_reason") or "").strip():\n            row_errors.append("major decision missing importance_reason")\n        suggestion = str(item.get("importance_suggestion") or "").lower().strip()\n        if suggestion in ALLOWED_DECISION and suggestion != decision:\n            row_warnings.append(f"importance_suggestion={suggestion} differs from decision={decision}")',
    )
    return text


def main() -> int:
    PATCH_SCRIPT.write_text(patch_workflow(PATCH_SCRIPT.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    GATE_SCRIPT.write_text(patch_gate(GATE_SCRIPT.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    compile(PATCH_SCRIPT.read_text(encoding="utf-8", errors="replace"), str(PATCH_SCRIPT), "exec")
    compile(GATE_SCRIPT.read_text(encoding="utf-8", errors="replace"), str(GATE_SCRIPT), "exec")
    print("[v106] runtime auto importance patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
