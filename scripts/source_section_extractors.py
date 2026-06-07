from __future__ import annotations

import re
from typing import Any


KO = {
    "new_class": "\uc2e0\uaddc \ud074\ub798\uc2a4",
    "class_change": "\ud074\ub798\uc2a4/\uc804\uc9c1",
    "class_balance": "\ud074\ub798\uc2a4 \ubc38\ub7f0\uc2a4",
    "skill_balance": "\uc2a4\ud0ac \ubc38\ub7f0\uc2a4",
    "new_system": "\uc2e0\uaddc \uc2dc\uc2a4\ud15c",
    "system_growth": "\uc2dc\uc2a4\ud15c/\uc131\uc7a5",
    "new_region": "\uc2e0\uaddc \uc9c0\uc5ed",
    "pve": "PvE \ucf58\ud150\uce20",
    "pve_balance": "PvE \ubc38\ub7f0\uc2a4",
    "pvp": "PvP/\uc804\uc7c1",
    "world": "\uc6d4\ub4dc \ucf58\ud150\uce20",
    "server": "\uc11c\ubc84/\uc6d4\ub4dc",
    "equipment": "\uc131\uc7a5/\uc7a5\ube44",
    "collection": "\uc131\uc7a5/\uc218\uc9d1",
    "spirit": "\uc131\uc7a5/\uc815\ub839",
    "event": "\uc774\ubca4\ud2b8/\ubcf4\uc0c1",
    "shop": "\uc0c1\uc810/BM",
    "ui": "\ud3b8\uc758/UI",
    "schedule": "\uc77c\uc815",
    "bug": "\ubc84\uadf8 \uc218\uc815",
}

CHANGE_WORDS = {
    "add": "\ucd94\uac00",
    "rework": "\uac1c\ud3b8",
    "improve": "\uac1c\uc120",
    "adjust": "\uc870\uc815",
    "change": "\ubcc0\uacbd",
    "start": "\uc2dc\uc791",
    "end": "\uc885\ub8cc",
    "expand": "\ud655\uc7a5",
    "support": "\uc9c0\uc6d0",
    "renew": "\uac31\uc2e0",
    "nerf": "\ud558\ud5a5",
    "buff": "\uc0c1\ud5a5",
    "fix": "\uc218\uc815",
    "run": "\uc9c4\ud589",
}

SECTION_GAMES = {"MIR4_KR", "MIR4_Global", "NightCrows_Global"}
REPRESENTATIVE_GAMES = {"Odin_KR", "NightCrows_KR"}

CHANGE_SUFFIXES = "|".join(re.escape(x) for x in CHANGE_WORDS.values())
LOW_VALUE_TARGETS = {
    "events",
    "event",
    "eventupdates",
    "newevents",
    "updates",
    "mainupdates",
    "\uc774\ubca4\ud2b8\uc5c5\ub370\uc774\ud2b8",
    "\ucd94\uac00",
    "\ubcc0\uacbd",
    "\uac1c\uc120",
    "\uc8fc\uc694\uc548\ub0b4\uc0ac\ud56d",
    "\uc548\ub0b4\uc0ac\ud56d",
}
TABLE_TARGET_PATTERN = re.compile(
    r"(^\(?\ucd94\uac00\)?\s|^[\uff0a*]?\s*\ubcc0\uacbd[:\s]|^\ubcc0\uacbd\s+|\uac1c\uc120\s*\ubc0f\s*\uac1c\uc120|\ub2e8\uacc4$|\ubcc0\uacbd\s*(?:\uc804|\ud6c4)|\uc0c1\ud488\uba85|\uad6c\uc131\ud488|\uad6c\ub9e4\s*\uc81c\ud55c|\uc218\ub7c9|\uac00\uaca9|\ud655\ub960|\ubcf4\uc0c1\s*\uc815\ubcf4)",
    re.I,
)

MAJOR_SIGNALS = {
    "new_class",
    "new_system",
    "new_region",
    "new_pve_content",
    "new_pvp_war",
    "new_world_content",
    "server_merge",
    "server_transfer",
    "major_rework",
}


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_key(text: str) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", str(text or "").lower())


def clean_line(line: str) -> str:
    line = compact_text(line)
    line = re.sub(r"^[.\u3002]\s*", "", line)
    line = re.sub(r"^[\u2022\u00b7\u318d\u25a0\u25cf\u226b\u25b6\u25b7\-*]+\s*", "", line)
    line = re.sub(r"^\(?\d{1,2}\)?[.)]\s*", "", line)
    return line.strip()


def is_bullet_line(line: str) -> bool:
    return re.match(r"^\s*[\-\u2022\u00b7\u318d\u25a0\u25cf*]\s*", str(line or "")) is not None


def is_table_or_link_line(line: str) -> bool:
    t = clean_line(line)
    if not t:
        return True
    if re.match(r"^\[.+\]$", t):
        return True
    if t in {"\ubd84\ub958", "\uae30\uc874", "\ubcc0\uacbd", "\ub2e8\uacc4", "\uc9c4\ud589 \uc77c\uc815", "\ud654\uc694\uc77c \uacbd\uae30", "\ud1a0\uc694\uc77c \uacbd\uae30"}:
        return True
    if re.match(r"^\d{1,3}(,\d{3})*(\s*~\s*\d{1,3}(,\d{3})*)?$", t):
        return True
    return False


def is_heading_like(line: str) -> bool:
    t = clean_line(line)
    if not t or t.endswith((".", "\ub2e4.", "\ub2c8\ub2e4.", "\ub2e4")):
        return False
    if len(t) > 32:
        return False
    if re.match(r"^\d{1,2}\s*\uc6d4\s*\d{1,2}\s*\uc77c|^\d{1,2}/\d{1,2}|^\d{4}\ub144", t):
        return False
    if re.search(r"(\d{1,2}:\d{2}|~|\uc885\ub8cc\s*\uc2dc|\ubcc0\uacbd\s*\ub0b4\uc6a9|\ucd94\uac00\s*\uc0ac\ud56d)", t):
        return False
    if t in {"\ubcc0\uacbd \ubc0f \ucd94\uac00", "\ucd94\uac00 \ubc0f \ubcc0\uacbd"}:
        return False
    if re.search(r"(\uc0ac\uc6a9\ud558\uc5ec|\ud65c\uc6a9\ud55c|\uc720\ubc1c|\uc99d\uac00|\uac10\uc18c|\ud53c\ud574|\ub300\uc0c1|\ud655\ub960|\uc7ac\uc0ac\uc6a9|\uc720\uc9c0)", t):
        return False
    return re.search(r"(\ucd94\uac00|\ubcc0\uacbd|\uc870\uc815|\uac1c\uc120|\uac1c\ud3b8|\uc2dc\uc791|\uc885\ub8cc|\ubc38\ub7f0\uc2a4|balance|class change|\ud074\ub798\uc2a4\s*\uccb4\uc778\uc9c0|\ud06c\ub8e8\uc138\uc774\ub4dc|\uc2dc\uc98c|\uae30\ub2a5)", t, re.I) is not None


def balance_target_line(line: str) -> str:
    t = clean_line(line)
    if not t:
        return ""
    m = re.match(r"^(.+?)\s*[:\uff1a]", t)
    if m:
        t = clean_line(m.group(1))
    if re.search(r"(\ubc38\ub7f0\uc2a4|balance|\uae30\uc220\s*\ud6a8\uacfc|\ud2b9\uc131|\ubcc0\uacbd|\ucd94\uac00|\ub4f1\uae09|\uae30\uc220\uba85|\ub808\ubca8)", t, re.I):
        return ""
    if len(t) > 20:
        return ""
    if re.search(r"[\d%~\u2192]", t):
        return ""
    if t in {"\ud76c\uadc0", "\uc601\uc6c5", "\uc804\uc124", "\uc77c\ubc18", "\uace0\uae09", "\ub4f1\uae09", "\uae30\uc220\uba85"}:
        return ""
    if re.search(r"(\ub2e8\uac80|\uc9c0\ud321\uc774|\uad81\uc218|\uc804\uc0ac|\ub9c8\ubc95\uc0ac|\ub808\uc774\ud53c\uc5b4|sword|dagger|staff|wand|class)", t, re.I):
        return t
    return ""


def split_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = compact_text(raw)
        if not line:
            continue
        if line in {"|", "-", "\u00a0"}:
            continue
        out.append(line)
    return out


def quoted(text: str) -> str:
    patterns = [
        r"[\u2018\u2019'\"<\[]([^'\u2018\u2019\"<>\[\]]{2,80})[\u2018\u2019'\">\]]",
        r"\u2018([^\u2019]{2,80})\u2019",
        r"\u201c([^\u201d]{2,80})\u201d",
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "")
        if m:
            return compact_text(m.group(1))
    return ""


def normalize_target(target: str) -> str:
    target = compact_text(target)
    target = target.strip(" .\u3002")
    target = re.sub(r"^(?:A|An)\s+new\s+", "", target, flags=re.I).strip()
    target = re.sub(r"^(New|new|\uc2e0\uaddc)\s+", "", target).strip()
    target = re.sub(r"\s+(will\s+(?:be\s+)?(?:added|adjusted|commence|begin|improved|changed|updated|introduced))\.?$", "", target, flags=re.I)
    target = re.sub(r"\s+(added|introduced|adjusted|improved|changed|updated|commenced|began|started|ended|closed|opened)\.?$", "", target, flags=re.I)
    target = re.sub(r"\s*(?:\ud604\uc0c1\uc774\s*)?\uc218\uc815\ub429\ub2c8\ub2e4\.?$", "", target)
    target = re.sub(rf"\s+(?:{CHANGE_SUFFIXES})$", "", target)
    target = re.sub(r"\s*(\uc774|\uac00|\uc744|\ub97c|\uc740|\ub294)\s*$", "", target)
    return target.strip(" :-")


def strip_change_suffix(target: str) -> str:
    target = compact_text(target).strip(" .\u3002")
    target = re.sub(r"\s+(?:added|introduced|adjusted|improved|changed|updated|commenced|began|started|ended|closed|opened)\.?$", "", target, flags=re.I)
    target = re.sub(rf"\s+(?:{CHANGE_SUFFIXES})$", "", target)
    return target.strip(" :-")


def english_target_change(text: str) -> tuple[str, str] | None:
    t = compact_text(text).strip()
    m = re.match(
        r"^(.+?)\s+(?:will\s+(?:be\s+)?)?(added|introduced|adjusted|improved|changed|updated|commence|commenced|begin|begins|started|ended|closed|opened)\.?$",
        t,
        re.I,
    )
    if not m:
        return None
    target = normalize_target(m.group(1))
    change = change_type(m.group(2))
    if not target:
        return None
    return target, change


def normalize_event_target(target: str, source: str, change: str) -> tuple[str, str, list[str]]:
    low = f"{target} {source}".lower()
    key = norm_key(target)
    m = re.search(r"\b(\d{1,3})\s+new\s+events?\b", low)
    if m:
        return f"\uc2e0\uaddc \uc774\ubca4\ud2b8 {m.group(1)}\uc885", CHANGE_WORDS["add"], ["NORMALIZED_EVENT_COUNT"]
    if key in {"events", "event", "newevents"}:
        return "\uc2e0\uaddc \uc774\ubca4\ud2b8", CHANGE_WORDS["run"], ["NORMALIZED_GENERIC_EVENT"]
    if key in {"eventupdates", "updates"}:
        return "\uc774\ubca4\ud2b8", CHANGE_WORDS["renew"], ["NORMALIZED_EVENT_UPDATE"]
    return target, change, []


def normalize_server_target(target: str, source: str, change: str) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    q = quoted(source)
    if q:
        target = q
    source_key = norm_key(source)
    if not target or norm_key(target) in {norm_key("\uc11c\ubc84"), "server", "world"}:
        if "\uc2e0\uaddc\uc11c\ubc84" in source_key or "newserver" in source_key:
            target = "\uc2e0\uaddc \uc11c\ubc84"
            flags.append("NORMALIZED_GENERIC_SERVER")
        else:
            target = "\uc11c\ubc84"
    elif re.match(r"^\uc11c\ubc84\s+\S+", target):
        m = re.match(r"^\uc11c\ubc84\s+(.+)$", target)
        target = f"{m.group(1)} \uc11c\ubc84" if m else target
        flags.append("NORMALIZED_SERVER_NAME")
    elif not re.search(r"(\uc11c\ubc84|\uc6d4\ub4dc|server|world)", target, re.I):
        target = f"{target} \uc11c\ubc84"
        flags.append("NORMALIZED_SERVER_NAME")
    return target, change, flags


def normalize_bug_target(target: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    target = re.sub(r"\s*(?:\ud604\uc0c1\uc774\s*)?\uc218\uc815\ub429\ub2c8\ub2e4\.?$", "", target)
    target = re.sub(r"\s*(?:\uac31\uc2e0|\ud45c\uc2dc|\uc801\uc6a9|\ub178\ucd9c|\uc791\ub3d9|\uc9c4\ud589|\ud68d\ub4dd|\ubc18\uc601)\ub418\uc9c0\s*\uc54a(?:\ub294)?$", "", target)
    target = re.sub(r"\s*(?:\ub418\uc9c0|\uc9c0)\s*\uc54a$", "", target)
    target = re.sub(r"\s*(\uc774|\uac00|\uc744|\ub97c|\uc740|\ub294)\s*$", "", target).strip()
    if target and "\uc624\ub958" not in target:
        target = f"{target} \uc624\ub958"
        flags.append("NORMALIZED_BUG_TARGET")
    return target, flags


def normalize_target_change(domain: str, target: str, change: str, title: str, detail: str) -> tuple[str, str, list[str]]:
    source = compact_text(f"{title} {detail}")
    flags: list[str] = []
    detected = english_target_change(target) or english_target_change(clean_line(title))
    if detected:
        target, change = detected
        flags.append("NORMALIZED_ENGLISH_VERB")
    target = normalize_target(strip_change_suffix(target))
    if domain == KO["event"]:
        target, change, added = normalize_event_target(target, source, change)
        flags.extend(added)
    if domain == KO["server"]:
        target, change, added = normalize_server_target(target, source, change)
        flags.extend(added)
    if domain == KO["shop"]:
        key = norm_key(target)
        if key in {"seasonpass", norm_key("\uc2dc\uc98c \ud328\uc2a4")}:
            target = "Season Pass" if re.search(r"season\s*pass", source, re.I) else "\uc2dc\uc98c \ud328\uc2a4"
            flags.append("NORMALIZED_SHOP_TARGET")
        elif key in {norm_key("\uc0c1\ud488"), "product"} and change == CHANGE_WORDS["add"]:
            target = "\uc2e0\uaddc \uc0c1\ud488"
            flags.append("NORMALIZED_SHOP_TARGET")
    if domain == KO["bug"]:
        target, added = normalize_bug_target(target)
        flags.extend(added)
    if not target:
        target = clean_line(title)
    target = strip_change_suffix(target)
    return target, change, flags


def quality_flags_for_summary(sentence: str, domain: str, target: str, change: str) -> list[str]:
    flags: list[str] = []
    key = norm_key(target)
    if not target:
        flags.append("EMPTY_TARGET")
    if key in LOW_VALUE_TARGETS:
        flags.append("GENERIC_TARGET")
    if TABLE_TARGET_PATTERN.search(target):
        flags.append("TABLE_ROW_TARGET")
    if re.search(rf"(?:{CHANGE_SUFFIXES})\s+{re.escape(change)}$", sentence):
        flags.append("DUPLICATE_CHANGE_WORD")
    if re.search(r"\b(added|introduced|adjusted|improved|changed|updated|commenced|started|ended|closed|opened)\.?\s+(?:%s)\b" % CHANGE_SUFFIXES, sentence, re.I):
        flags.append("ENGLISH_VERB_KO_SUFFIX")
    if domain in {KO["class_balance"], KO["skill_balance"]} and TABLE_TARGET_PATTERN.search(sentence):
        flags.append("BALANCE_TABLE_ROW")
    if len(target) > 80:
        flags.append("OVERLONG_TARGET")
    return flags


def change_type(text: str) -> str:
    low = str(text or "").lower()
    compact = norm_key(text)
    if re.search(r"\b(end|ended|expires?|closed?)\b", low) or "\uc885\ub8cc" in compact:
        return CHANGE_WORDS["end"]
    if any(x in low for x in ["commence", "begin", "start", "open"]) or "\uc2dc\uc791" in compact:
        return CHANGE_WORDS["start"]
    if any(x in low for x in ["improved", "improvement"]) or "\uac1c\uc120" in compact:
        return CHANGE_WORDS["improve"]
    if any(x in low for x in ["adjusted", "adjustment"]) or "\uc870\uc815" in compact:
        return CHANGE_WORDS["adjust"]
    if re.search(r"\b(changed|change)\b", low) or "\ubcc0\uacbd" in compact:
        return CHANGE_WORDS["change"]
    if any(x in low for x in ["renewed", "updated"]) or "\uac31\uc2e0" in compact:
        return CHANGE_WORDS["renew"]
    if any(x in low for x in ["fixed", "fix"]) or "\uc218\uc815" in compact:
        return CHANGE_WORDS["fix"]
    if "\ud558\ud5a5" in compact or "decreased" in low:
        return CHANGE_WORDS["nerf"]
    if "\uc0c1\ud5a5" in compact or "increased" in low:
        return CHANGE_WORDS["buff"]
    return CHANGE_WORDS["add"]


def balance_targets(title: str, detail: str) -> list[str]:
    text = f"{title}\n{detail}"
    targets: list[str] = []
    for line in split_lines(text):
        cleaned = clean_line(line)
        if not cleaned:
            continue
        if TABLE_TARGET_PATTERN.search(cleaned):
            continue
        if re.match(r"^(PvE|PVE|PVP|PvP|UI|BM)$", cleaned, re.I):
            continue
        if re.search(r"(\ubc38\ub7f0\uc2a4|balance)", cleaned, re.I):
            continue
        if len(cleaned) <= 20 and not re.search(r"[\ucd94\uac00\uc870\uc815\ubcc0\uacbd\uc218\uc815]", cleaned):
            targets.append(cleaned)
    out: list[str] = []
    seen: set[str] = set()
    for target in targets:
        key = norm_key(target)
        if key and key not in seen:
            seen.add(key)
            out.append(target)
    return out[:6]


def classify_unit(title: str, detail: str) -> tuple[str, str, list[str]]:
    text = f"{title} {detail}"
    low = text.lower()
    compact = norm_key(text)
    signals: list[str] = []

    if re.search(r"(\ubc38\ub7f0\uc2a4|balance)", text, re.I):
        domain = KO["class_balance"] if re.search(r"(\ud074\ub798\uc2a4|\uc9c1\uc5c5|class)", text, re.I) else KO["skill_balance"]
        return domain, CHANGE_WORDS["adjust"], ["class_balance"]

    if re.search(r"(new class|new combat class|\uc2e0\uaddc\s*(\ud074\ub798\uc2a4|\uc9c1\uc5c5))", text, re.I):
        return KO["new_class"], CHANGE_WORDS["add"], ["new_class"]
    if re.search(r"(class change|\ud074\ub798\uc2a4\s*\uccb4\uc778\uc9c0|\uc9c1\uc5c5\s*\ubcc0\uacbd)", text, re.I):
        return KO["class_change"], change_type(text), ["class_change"]
    if re.search(r"(new system|\uc2e0\uaddc\s*\uc2dc\uc2a4\ud15c|creed|potential)", text, re.I):
        return KO["new_system"], change_type(text), ["new_system"]
    if re.search(r"(new region|\uc2e0\uaddc\s*\uc9c0\uc5ed)", text, re.I):
        return KO["new_region"], CHANGE_WORDS["add"], ["new_region"]
    if re.search(r"(server transfer|server merge|\uc11c\ubc84\s*\uc774\uc804|\uc11c\ubc84\s*\ud1b5\ud569)", text, re.I):
        sig = "server_transfer" if re.search(r"(transfer|\uc774\uc804)", text, re.I) else "server_merge"
        return KO["server"], change_type(text), [sig]
    if re.search(r"(new server|server\s+(?:added|opened|closed)|growth server|boost(?:ing)? world|\uc2e0\uaddc\s*\uc11c\ubc84|\uc11c\ubc84\s*(?:\ucd94\uac00|\uc885\ub8cc|\uc624\ud508|\uac1c\uc124)|\uc131\uc7a5\s*\uc11c\ubc84|\uc2dc\uc98c\s*\uc11c\ubc84)", text, re.I):
        if re.search(r"(closed|\uc885\ub8cc)", text, re.I):
            sig = "server_closed"
        elif re.search(r"(new|added|opened|\uc2e0\uaddc|\ucd94\uac00|\uc624\ud508|\uac1c\uc124)", text, re.I):
            sig = "new_server"
        else:
            sig = "server_change"
        return KO["server"], change_type(text), [sig]
    if re.search(r"(world battlefront|battlefront|crusade|\ud06c\ub8e8\uc138\uc774\ub4dc|\uc601\uc9c0)", text, re.I):
        sig = "new_world_content" if re.search(r"(new|\uc2e0\uaddc|\ucd94\uac00)", text, re.I) else "world_content"
        return KO["world"], change_type(text), [sig]
    if re.search(r"(dungeon|boss|raid|monster|\uc9c0\ud558\uac10\uc625|\ub358\uc804|\ubcf4\uc2a4|\ubaac\uc2a4\ud130|\ud544\ub4dc)", text, re.I):
        if re.search(r"(\uccb4\ub825|\ub370\ubbf8\uc9c0|\ub09c\uc774\ub3c4|\ud558\ud5a5|difficulty|damage)", text, re.I):
            return KO["pve_balance"], change_type(text), ["pve_balance"]
        sig = "new_pve_content" if re.search(r"(new|\uc2e0\uaddc|\uc0c8\ub86d\uac8c|\ucd94\uac00)", text, re.I) else "pve_content"
        return KO["pve"], change_type(text), [sig]
    if re.search(r"(item collection|\uc544\uc774\ud15c\s*\uc218\uc9d1|\uc218\uc9d1)", text, re.I):
        return KO["collection"], change_type(text), ["collection"]
    if re.search(r"(spirit|\uc815\ub839)", text, re.I):
        return KO["spirit"], change_type(text), ["spirit"]
    if re.search(r"(artifact|inner armor|weapon style|equipment|gear|mount|glider|accessory|lamp|\uc7a5\ube44|\uc7a5\uc2e0\uad6c|\ud0c8\uac83|\uae00\ub77c\uc774\ub354|\ubb34\uae30\s*\uc678\ud615|\ubc24\uae4c\ub9c8\uadc0)", text, re.I):
        return KO["equipment"], change_type(text), ["equipment"]
    if re.search(r"(shop|pass|product|purchase|merchant|package|cash shop|\uc0c1\uc810|\ud328\uc2a4|\uc0c1\ud488|\ud328\ud0a4\uc9c0|\uad6c\ub9e4|\ud310\ub9e4|\uc18c\ud658\uad8c|\uce90\uc2dc\uc0f5)", text, re.I):
        return KO["shop"], change_type(text), ["shop"]
    if re.search(r"(event|check-in|attendance|\uc774\ubca4\ud2b8|\ucd9c\uc11d|\ubbf8\uc158)", text, re.I):
        change = CHANGE_WORDS["run"] if re.search(r"(\uc774\ubca4\ud2b8)", text, re.I) else change_type(text)
        return KO["event"], change, ["event"]
    if re.search(r"(\bui\b|convenience|display|image|\uc774\ubbf8\uc9c0|\ud3b8\uc758|\ud45c\uc2dc|\uc808\uc804\ubaa8\ub4dc)", text, re.I):
        return KO["ui"], change_type(text), ["ui"]
    if re.search(r"(schedule|\uc77c\uc815)", text, re.I):
        return KO["schedule"], change_type(text), ["schedule"]
    if re.search(r"(bug|issue|fix|\ubc84\uadf8|\uc624\ub958|\ud604\uc0c1)", text, re.I):
        return KO["bug"], CHANGE_WORDS["fix"], ["bug_fix"]
    return KO["system_growth"], change_type(text), ["system_growth"]


def target_from_unit(title: str, detail: str, domain: str) -> str:
    if domain in {KO["class_balance"], KO["skill_balance"]}:
        targets = balance_targets(title, detail)
        return ", ".join(targets) if targets else clean_line(title)

    text = clean_line(title)
    if domain == KO["new_class"]:
        q = quoted(detail) or quoted(text)
        return normalize_target(q or text)
    if domain == KO["event"]:
        m = re.search(r"(\uc2e0\uaddc\s*\uc774\ubca4\ud2b8)", text)
        if m:
            return m.group(1)
    if domain == KO["shop"]:
        m = re.search(r"(\uc2e0\uaddc\s*(?:\uc0c1\ud488|\ud328\ud0a4\uc9c0))", text)
        if m:
            return m.group(1)
    if domain == KO["server"]:
        q = quoted(detail) or quoted(text)
        if q:
            return normalize_target(q)
    if domain == KO["pve_balance"] or (re.search(r"\(.+\)", text) and not re.search(r"\)\s+(\ucd94\uac00|\uac1c\ud3b8|\uac1c\uc120|\uc870\uc815|\ubcc0\uacbd|\uc2dc\uc791|\uc885\ub8cc|\uc9c4\ud589)", text)):
        return normalize_target(text)
    if re.search(r"^(\uae30\ud0c0\s*)?(\uac1c\uc120|\ubcc0\uacbd)\s*\uc0ac\ud56d$", text) and clean_line(detail):
        return normalize_target(clean_line(detail))
    if domain == KO["class_change"]:
        return normalize_target(text)
    patterns = [
        r"^(?:New|new)\s+[^:]{2,30}:\s*(.+)$",
        r"^(.+?)\s+will\s+(?:be\s+)?(?:added|adjusted|improved|changed|commence|begin|introduced|updated)",
        r"^(.+?)\s+(?:added|introduced|adjusted|improved|changed|updated|commenced|started|ended|closed|opened)\.?$",
        r"^(.+?)\s+(?:\ucd94\uac00|\uac1c\ud3b8|\uac1c\uc120|\uc870\uc815|\ubcc0\uacbd|\uc2dc\uc791|\uc885\ub8cc|\uc9c4\ud589)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return normalize_target(m.group(1))
    q = quoted(text) or quoted(detail)
    if q:
        return normalize_target(q)
    return normalize_target(text)


def build_summary_unit(game: str, title: str, detail: str, order: int) -> dict[str, Any]:
    domain, change, signals = classify_unit(title, detail)
    target = target_from_unit(title, detail, domain)
    if domain in {KO["class_balance"], KO["skill_balance"]} and not target:
        target = clean_line(title)
    target, change, normalization_flags = normalize_target_change(domain, target, change, title, detail)
    sentence = f"{domain}: {target} {change}".strip()
    quality_flags = quality_flags_for_summary(sentence, domain, target, change)
    return {
        "order": order,
        "domain": domain,
        "target": target,
        "change_type": change,
        "signals": signals,
        "normalization_flags": normalization_flags,
        "quality_flags": quality_flags,
        "source_heading": clean_line(title),
        "source_context_excerpt": clean_line(detail),
        "summary_sentence": sentence,
        "confidence": 0.9,
        "profile_rule": "source_section_extractor_v1",
    }


def find_section(lines: list[str], start_patterns: list[str], end_patterns: list[str], max_lines: int = 220) -> list[str]:
    start = -1
    for i, line in enumerate(lines):
        if any(re.search(p, line, re.I) for p in start_patterns):
            start = i + 1
            break
    if start < 0:
        return []
    out: list[str] = []
    for line in lines[start:]:
        if out and any(re.search(p, line, re.I) for p in end_patterns):
            break
        out.append(line)
        if len(out) > max_lines:
            break
    return out


def parse_numbered_main_updates(game: str, section: list[str]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    current_title = ""
    details: list[str] = []
    pending_number = False

    def flush() -> None:
        nonlocal current_title, details
        if current_title:
            detail = " ".join(clean_line(x) for x in details[:2] if clean_line(x))
            units.append(build_summary_unit(game, current_title, detail, len(units) + 1))
        current_title = ""
        details = []

    for line in section:
        if re.search(r"^[\[\u25c7\u25c6\u25a0\u25cf\u25c8\s]*(?:In-Game Updates|Main Updates|Update Summary)[\]\u25c7\u25c6\u25a0\u25cf\u25c8\s]*$", line, re.I):
            continue
        if re.match(r"^\s*\d{1,2}[.)]\s*$", line):
            flush()
            pending_number = True
            continue
        if pending_number:
            current_title = clean_line(line)
            pending_number = False
            continue
        m = re.match(r"^\s*(\d{1,2})[.]\s*(.+)$", line)
        if m:
            flush()
            current_title = clean_line(m.group(2))
            continue
        if current_title and is_bullet_line(line):
            details.append(line)
        elif current_title and len(details) < 1 and not re.match(r"^[\[\]#<]", line):
            if not re.search(r"(Patch Note Details|Update Details|Known Issues)", line, re.I):
                details.append(line)
    flush()
    return units[:12]


def parse_first_numbered_block(game: str, lines: list[str]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    started = False
    for line in lines:
        cleaned = clean_line(line)
        if re.search(r"(\ud328\uce58\s*\ub178\ud2b8\s*\]|\bPatch Note Details\b|\bUpdate Details\b|^\u25a0)", cleaned, re.I):
            if started:
                break
        m = re.match(r"^\s*(\d{1,2})[.)]\s*(.+)$", line)
        if not m:
            if started and len(units) >= 2:
                break
            continue
        title = clean_line(m.group(2))
        if not title or is_table_or_link_line(title):
            continue
        if len(title) > 90:
            continue
        started = True
        units.append(build_summary_unit(game, title, "", len(units) + 1))
        if len(units) >= 12:
            break
    return dedupe_units(units)


def parse_representative_items(game: str, section: list[str]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    n = len(section)

    def title_at(idx: int) -> str:
        if idx < 0 or idx >= n:
            return ""
        line = section[idx]
        if re.match(r"^\s*\d{1,2}\)\s+", line):
            return ""
        m = re.match(r"^\s*(\d{1,2})[.]\s*(.+)$", line)
        if m:
            return clean_line(m.group(2))
        cleaned = clean_line(line)
        if 3 <= len(cleaned) <= 80 and is_heading_like(line) and not is_bullet_line(line) and not is_table_or_link_line(line):
            if re.search(r"(\ucd94\uac00|\ubcc0\uacbd|\uc870\uc815|\uac1c\uc120|\uac1c\ud3b8|\uc2dc\uc791|\uc885\ub8cc|\ubc38\ub7f0\uc2a4|balance|\ud074\ub798\uc2a4\s*\uccb4\uc778\uc9c0|\uc2dc\uc98c|\uae30\ub2a5)", cleaned, re.I):
                return cleaned
            lookahead = section[idx + 1 : min(n, idx + 5)]
            if any(is_bullet_line(x) for x in lookahead):
                return cleaned
        return ""

    i = 0
    while i < n and len(units) < 20:
        title = title_at(i)
        if not title:
            i += 1
            continue
        details: list[str] = []
        j = i + 1
        is_balance = re.search(r"(\ubc38\ub7f0\uc2a4|balance)", title, re.I) is not None
        while j < n:
            nxt = section[j]
            if title_at(j):
                break
            if is_bullet_line(nxt):
                if not is_table_or_link_line(nxt):
                    details.append(nxt)
                if not is_balance:
                    break
            elif is_balance:
                target = balance_target_line(nxt)
                if target:
                    details.append(target)
            if len(details) >= 8:
                break
            j += 1
        joiner = "\n" if is_balance else " "
        detail_text = joiner.join(clean_line(x) for x in details if clean_line(x))
        units.append(build_summary_unit(game, title, detail_text, len(units) + 1))
        i = max(j, i + 1)
    return units


def parse_numbered_representative_items(game: str, section: list[str]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    i = 0
    while i < len(section) and len(units) < 20:
        line = section[i]
        m = re.match(r"^\s*(\d{1,2})[.)]\s*(.+)$", line)
        if not m:
            i += 1
            continue
        title = clean_line(m.group(2))
        details: list[str] = []
        j = i + 1
        while j < len(section):
            nxt = section[j]
            if re.match(r"^\s*\d{1,2}[.)]\s+", nxt):
                break
            if is_bullet_line(nxt):
                details.append(nxt)
                break
            j += 1
        detail_text = " ".join(clean_line(x) for x in details if clean_line(x))
        units.append(build_summary_unit(game, title, detail_text, len(units) + 1))
        i = max(j, i + 1)
    return units


def parse_odin_roman_fallback(game: str, lines: list[str]) -> list[dict[str, Any]]:
    start = -1
    for i, line in enumerate(lines):
        if "\u3010" in line and re.search(r"\uc5c5\ub370\uc774\ud2b8\s*\uc0c1\uc138\s*\ub0b4\uc5ed\s*\uc548\ub0b4", line):
            start = i + 1
    if start < 0:
        for i, line in enumerate(lines):
            if re.search(r"\uc544\ub798\ub97c\s*\ucc38\uace0|\uc5c5\ub370\uc774\ud2b8\uc5d0\s*\ub300\ud55c\s*\uc790\uc138\ud55c", line):
                start = i + 1
                break
    if start < 0:
        start = 0

    units: list[dict[str, Any]] = []
    current_title = ""
    numbered_titles: list[str] = []

    def is_noise(title: str) -> bool:
        t = clean_line(title)
        if not t:
            return True
        if t in {"\uae30\ud0c0 \ubcc0\uacbd \uc0ac\ud56d", "\ubcc0\uacbd \uc0ac\ud56d"}:
            return True
        if re.search(r"(\ud310\ub9e4\s*\ud0ed|\uc0c1\ud488\uba85|\uad6c\uc131\ud488|\uad6c\ub9e4\s*\uc81c\ud55c|\uc544\uc774\ud15c\s*\uba85|\uc218\uc9d1\s*\ud6a8\uacfc)", t):
            return True
        return False

    def choose_titles(section_title: str, children: list[str]) -> list[str]:
        title = clean_line(section_title)
        children = [clean_line(x) for x in children if clean_line(x) and not is_noise(x)]
        if not title:
            return children[:3]
        if re.search(r"(\uae30\ud0c0|\ubcc0\uacbd)", title) and children:
            return children[:4]
        return [title]

    def flush() -> None:
        nonlocal current_title, numbered_titles
        for title in choose_titles(current_title, numbered_titles):
            if len(units) >= 16:
                break
            units.append(build_summary_unit(game, title, "", len(units) + 1))
        current_title = ""
        numbered_titles = []

    i = start
    while i < len(lines):
        raw_line = lines[i]
        line = clean_line(raw_line)
        if re.search(r"(\ucd94\uac00\s*\uc548\ub0b4\s*\uc0ac\ud56d|\uac10\uc0ac\ud569\ub2c8\ub2e4|^\ub2e4\uc74c\uac80\uc0c9$|^\ub313\uae00$)", line):
            break
        if re.match(r"^[\u2160-\u216b]+$", line) or re.match(r"^[\u2160-\u216b]+\s*\.", line):
            flush()
            j = i + 1
            while j < len(lines) and clean_line(lines[j]) in {"", ".", "\u00b7"}:
                j += 1
            current_title = clean_line(lines[j]) if j < len(lines) else ""
            i = j + 1
            continue
        m = re.match(r"^\s*\d{1,2}\)\s*(.+)$", raw_line)
        if current_title and m:
            numbered_titles.append(clean_line(m.group(1)))
        i += 1
    flush()
    return dedupe_units(units)


def parse_nightcrows_kr_bullet_fallback(game: str, lines: list[str]) -> list[dict[str, Any]]:
    start = 0
    for i, line in enumerate(lines):
        if re.search(r"\uc790\uc138\ud55c\s*\uc0ac\ud56d|\uc544\ub798\s*\ub0b4\uc6a9|\ud558\ub2e8\uc758\s*\ub0b4\uc6a9", line):
            start = i + 1
            break

    units: list[dict[str, Any]] = []
    current_section = ""
    section_emitted = False
    section_pattern = re.compile(
        r"(\uc2e0\uaddc|\ucd94\uac00|\uac1c\uc120|\ubcc0\uacbd|\uc624\ub958|\uc218\uc815|\uc774\ubca4\ud2b8|\uc5f0\ud569|\ubc38\ub7f0\uc2a4|\ucf58\ud150\uce20|\ub358\uc804|\ubaac\uc2a4\ud130|\uc7a5\ube44|\ud074\ub798\uc2a4|\uc2dc\uc98c)"
    )

    def next_detail(idx: int) -> str:
        for nxt in lines[idx + 1 : min(len(lines), idx + 5)]:
            cleaned = clean_line(nxt)
            if not cleaned or is_table_or_link_line(cleaned):
                continue
            if is_bullet_line(nxt):
                cleaned = clean_line(nxt)
            if re.match(r"^[\u25a0\u203b*]|\uc774\ubca4\ud2b8\s*\uae30\uac04|^\uc608\uc2dc\d*$", cleaned):
                continue
            return cleaned
        return ""

    i = start
    while i < len(lines) and len(units) < 16:
        raw = lines[i]
        line = clean_line(raw)
        if re.search(r"(\uc990\uaca8\ucc3e\uae30|\uacf5\uc720\ud558\uae30|\ud68c\uc0ac\uc18c\uac1c|\uc774\uc6a9\uc57d\uad00|^\ubaa9\ub85d$)", line):
            break
        if not line:
            i += 1
            continue
        if not is_bullet_line(raw) and 2 <= len(line) <= 42 and section_pattern.search(line):
            current_section = line
            section_emitted = False
            if re.search(r"(\uc2e0\uaddc\s*\ucf58\ud150\uce20|\uc2e0\uaddc\s*\ubaac\uc2a4\ud130|\uc5f0\ud569|\ud074\ub798\uc2a4\s*\ubc38\ub7f0\uc2a4)", line):
                detail = next_detail(i)
                units.append(build_summary_unit(game, line, detail, len(units) + 1))
                section_emitted = True
            i += 1
            continue
        if is_bullet_line(raw):
            if re.match(r"^[\u2022\u00b7\u318d\u25a0\u25cf\-*]*\s*[\u203b\uff0a\u25a0]", raw):
                i += 1
                continue
            m = re.match(r"^[\u2022\u00b7\u318d\u25a0\u25cf\-*]*\s*\[([^\]]{1,20})\]", raw)
            if m:
                category = m.group(1)
                detail = next_detail(i)
                title = " ".join(x for x in [current_section, category, detail] if x)
                if detail and title and not is_table_or_link_line(title):
                    units.append(build_summary_unit(game, title, detail, len(units) + 1))
            elif current_section and not section_emitted and re.search(r"(\uc2e0\uaddc|\ucd94\uac00|\uac1c\uc120|\ubcc0\uacbd|\uc624\ub958|\uc218\uc815|\uc774\ubca4\ud2b8|\uc5f0\ud569|\ubc38\ub7f0\uc2a4|\ucf58\ud150\uce20|\ub358\uc804|\ubaac\uc2a4\ud130|\uc7a5\ube44|\ud074\ub798\uc2a4)", current_section):
                title = f"{current_section} {line}"
                units.append(build_summary_unit(game, title, line, len(units) + 1))
                section_emitted = True
        i += 1
    return dedupe_units(units)


def parse_nightcrows_kr_intro_fallback(game: str, lines: list[str]) -> list[dict[str, Any]]:
    intro: list[str] = []
    capture = False
    for line in lines:
        cleaned = clean_line(line)
        if "안녕하세요" in cleaned and "나이트 크로우" in cleaned:
            capture = True
            continue
        if capture and re.search(r"(\uc790\uc138\ud55c\s*\uc0ac\ud56d|\uc790\uc138\ud55c\s*\ub0b4\uc6a9|\ud558\ub2e8\uc758\s*\ub0b4\uc6a9|\uc544\ub798\s*\ub0b4\uc6a9)", cleaned):
            break
        if capture and cleaned:
            intro.append(cleaned)
    text = compact_text(" ".join(intro))
    if not text:
        return []
    parts = re.split(r"(?:\.\s+|\s*,\s*|\s+\ub354\ubd88\uc5b4\s+|\s+\uc774\uc640\s*\ud568\uaed8\s+)", text)
    units: list[dict[str, Any]] = []
    for part in parts:
        clause = clean_line(part)
        clause = re.sub(r"^(?:\uc774\ubc88\s*)?\uc5c5\ub370\uc774\ud2b8(?:\ub97c|\uc5d0\uc11c\ub294|\ub97c\s*\ud1b5\ud574)?\s*", "", clause)
        clause = re.sub(r"^(?:\uc774\ubc88\s*)?\uc784\uc2dc\s*\uc810\uac80\uc5d0\uc11c\ub294\s*", "", clause)
        clause = re.sub(r"^\ud1b5\ud574\s*", "", clause)
        clause = re.sub(r"^(?:\ub610\ud55c|,|\uacfc|,?\s*\uc774\uc640\s*\ud568\uaed8)\s*", "", clause)
        if re.search(r"(\uc548\ub0b4\ub4dc\ub9bd\ub2c8\ub2e4|\ucc38\uace0\ud574\uc8fc\uc2dc\uae30|\ud655\uc778\ud574\s*\uc8fc\uc2dc\uae30)", clause):
            continue
        if len(clause) < 8:
            continue
        if not re.search(r"(\ucd94\uac00|\uc870\uc815|\uac1c\uc120|\ubcc0\uacbd|\uc218\uc815|\uc9c4\ud589|\uc801\uc6a9|\uc0c1\ud5a5|\ud558\ud5a5|\uc2dc\uc791|\uc885\ub8cc|\ud655\uc7a5)", clause):
            continue
        units.append(build_summary_unit(game, clause, "", len(units) + 1))
        if len(units) >= 6:
            break
    return dedupe_units(units)


def dedupe_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        key = norm_key(unit.get("summary_sentence", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        unit = dict(unit)
        unit["order"] = len(out) + 1
        out.append(unit)
    return out[:16]


def extract_source_section_units(game: str, text: str) -> tuple[list[dict[str, Any]], list[str]]:
    lines = split_lines(text)
    flags: list[str] = []
    if game == "MIR4_KR":
        section = find_section(lines, [r"^\[?\s*\uc8fc\uc694\s*\uc5c5\ub370\uc774\ud2b8\s*\uc0ac\ud56d\s*\]?$"], [r"^\[.+\ud328\uce58\s*\ub178\ud2b8.*\]$", r"^\u25a0", r"^\[?\s*\uc0c1\uc138"])
        units = parse_numbered_main_updates(game, section)
        if not units:
            units = parse_first_numbered_block(game, lines)
    elif game == "MIR4_Global":
        section = find_section(lines, [r"^\[?\s*Main Updates\s*\]?$", r"Update Summary"], [r"Patch Note Details", r"Update Details", r"Known Issues", r"^\[.*Details.*\]$"])
        units = parse_numbered_main_updates(game, section)
        if not units:
            units = parse_first_numbered_block(game, lines)
    elif game == "NightCrows_Global":
        section = find_section(lines, [r"^\[?\s*Main Updates\s*\]?$"], [r"^Update Details$", r"^Patch Note Details$", r"Known Issues", r"Resolved Issues", r"^\[.*Details.*\]$"])
        units = parse_numbered_main_updates(game, section)
        if not units:
            units = parse_first_numbered_block(game, lines)
    elif game in REPRESENTATIVE_GAMES:
        section = find_section(
            lines,
            [
                r"\uc8fc\uc694\s*\uc548\ub0b4\s*\uc0ac\ud56d",
                r"\uc8fc\uc694\s*\uc5c5\ub370\uc774\ud2b8",
                r"\uc2e0\uaddc\s*\ucd94\uac00\s*\ubc0f\s*\ubcc0\uacbd\s*\uc0ac\ud56d",
                r"\uc2e0\uaddc\s*\ucf58\ud150\uce20\s*\ucd94\uac00\s*\ubc0f\s*\ubcc0\uacbd\s*\uc0ac\ud56d",
                r"\uc5c5\ub370\uc774\ud2b8\s*\uc0c1\uc138\s*\ub0b4\uc5ed",
            ],
            [
                r"^\u2161\.",
                r"^\u2162\.",
                r"^\u2163\.",
                r"^\uc2e0\uaddc\s*\uc774\ubca4\ud2b8$",
                r"\uc0c1\uc138\s*\uc548\ub0b4",
                r"\uc5c5\ub370\uc774\ud2b8\s*\uc0c1\uc138",
                r"\ud328\uce58\s*\ub178\ud2b8\s*\uc0c1\uc138",
                r"\uc774\ubca4\ud2b8\s*\uc548\ub0b4",
                r"\uc0c1\ud488\s*\uc548\ub0b4",
                r"\uc624\ub958\s*\uc218\uc815",
                r"^\uac1c\uc120\s*\uc0ac\ud56d$",
            ],
            max_lines=900,
        )
        units = parse_numbered_representative_items(game, section) if game == "Odin_KR" else parse_representative_items(game, section)
        if game == "Odin_KR" and not units:
            units = parse_odin_roman_fallback(game, lines)
        if game == "NightCrows_KR" and not units:
            units = parse_nightcrows_kr_intro_fallback(game, lines)
        if game == "NightCrows_KR" and not units:
            units = parse_nightcrows_kr_bullet_fallback(game, lines)
    else:
        return [], ["UNSUPPORTED_GAME"]

    units = dedupe_units(units)
    if not units:
        flags.append("SUMMARY_SECTION_NOT_FOUND_OR_EMPTY")
    return units, flags


def section_summary_preview(game: str, text: str) -> dict[str, Any]:
    units, flags = extract_source_section_units(game, text)
    raw_units = units
    units = [u for u in raw_units if not (u.get("quality_flags") or [])]
    dropped_quality_flags: list[str] = []
    for unit in raw_units:
        for flag in unit.get("quality_flags", []) or []:
            if flag not in dropped_quality_flags:
                dropped_quality_flags.append(flag)
    if raw_units and not units:
        flags.extend([flag for flag in dropped_quality_flags if flag not in flags])
    body = [str(u.get("summary_sentence", "")) for u in units if u.get("summary_sentence")]
    if game == "NightCrows_KR":
        suspicious = [
            line for line in body
            if re.search(r"(:\s*(?:\uff0a|\u203b|\(?\ucd94\uac00\)?|\(?\ubcc0\uacbd\)?|\uc9c0\uc5ed\uba85)|\uc885\ub8cc\s*\uc774\ubca4\ud2b8|\uae30\ud0c0\s*\ubcc0\uacbd|\uc2dc\uc98c\s*\ud328\uc2a4)", line)
        ]
        if suspicious and len(suspicious) >= max(2, len(body) // 2):
            flags.append("LOW_CONFIDENCE_REPRESENTATIVE_SECTION")
    tags: list[str] = []
    signals: list[str] = []
    for unit in units:
        domain = str(unit.get("domain", ""))
        if domain and domain not in tags:
            tags.append(domain)
        for signal in unit.get("signals", []) or []:
            if signal not in signals:
                signals.append(signal)
    return {
        "body_summary": body,
        "domain_tags": tags,
        "card_summary": " \u00b7 ".join(tags[:4]),
        "units": units,
        "signals": signals,
        "quality_status": "PASS" if body and not flags else "REVIEW",
        "flags": flags,
        "quality_warnings": dropped_quality_flags,
    }


def major_from_signals(signals: list[str]) -> bool:
    return any(signal in MAJOR_SIGNALS for signal in signals or [])
