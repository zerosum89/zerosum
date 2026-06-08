from __future__ import annotations

import re
from typing import Any


KO = {
    "new_class": "신규 클래스",
    "class_change": "클래스/전직",
    "class_balance": "클래스 밸런스",
    "skill_balance": "스킬 밸런스",
    "new_system": "신규 시스템",
    "system_growth": "시스템/성장",
    "new_region": "신규 지역",
    "pve": "PvE 콘텐츠",
    "pve_balance": "PvE 밸런스",
    "pvp": "PvP/전쟁",
    "world": "월드 콘텐츠",
    "server": "서버/월드",
    "equipment": "성장/장비",
    "collection": "성장/수집",
    "spirit": "성장/정령",
    "event": "이벤트/보상",
    "shop": "상점/BM",
    "ui": "편의/UI",
    "schedule": "일정",
    "bug": "버그 수정",
}

CHANGE_WORDS = {
    "add": "추가",
    "rework": "개편",
    "improve": "개선",
    "adjust": "조정",
    "change": "변경",
    "start": "시작",
    "end": "종료",
    "expand": "확장",
    "support": "지원",
    "renew": "갱신",
    "nerf": "하향",
    "buff": "상향",
    "fix": "수정",
    "run": "진행",
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
    "이벤트업데이트",
    "추가",
    "변경",
    "개선",
    "신규",
    "이벤트",
    "아이콘",
    "주요안내사항",
    "안내사항",
}
TABLE_TARGET_PATTERN = re.compile(
    r"(^\(?추가\)?\s|^[＊*]?\s*변경[:\s]|^변경\s+|\[[^\]]+\]|\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}|\bx\s*\d+\b|^\d+\s*초\s|진행\s*기간|^발동\s*조건|^사용\s*기술|개선\s*및\s*개선|\d+\s*(?:단계|페이즈)$|\d+\s*(?:단계|페이즈)\s*추가|변경\s*(?:전|후)|상품명|구성품|구매\s*제한|수량|가격|확률|보상\s*정보)",
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
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").lower())


# ── Named-content detection (A/B gate) ───────────────────────────────────────

GENERIC_NOUN_ONLY = {
    "기능", "편의", "편의성", "정보", "표시", "조작", "운영", "진행", "시스템", "처리",
    "구성", "조건", "개선", "향상", "조정", "추가", "변경", "강화", "확장", "갱신",
    "수정", "지원", "제공", "반영", "적용", "실행", "완료", "업데이트", "개편",
    "안내", "공지", "일정", "기타", "내용", "사항", "일부", "전반", "전체", "기존",
}


def has_named_content(text: str) -> bool:
    """인용구·영어 고유명사·콘텐츠명 등 구체적 대상이 있으면 True."""
    if not text:
        return False
    # 인용구: '도미니언', "Dragon Forge", 「...」 등
    if re.search(r"['‘’“”\"\<\[「『【].{2,60}['‘’“”\"\>\]」』】]", text):
        return True
    # 영어 대문자 고유명사 (두 글자 이상 연속)
    if re.search(r"\b[A-Z][a-zA-Z]{2,}\b", text):
        return True
    # 서버명 패턴: "이벨린 서버", "아스가르드 서버"
    if re.search(r"[가-힣]{2,10}\s*서버", text):
        return True
    # 클래스/직업명 패턴 (짧은 한글 단어가 단독으로 있는 경우)
    if re.search(r"(궁수|마법사|전사|기사|암살자|사제|무사|검사|워리어|레인저|위저드|소서러|로그|나이트|팔라딘|버서커)", text, re.I):
        return True
    return False


def is_vague_target(target: str) -> bool:
    """target이 고유명사 없이 generic 행위 명사만으로 구성되면 True (A 규칙)."""
    if not target or len(target.strip()) < 2:
        return True
    if has_named_content(target):
        return False
    words = set(re.findall(r"[가-힣]+", target))
    if not words:
        # 영어만 있는 경우는 이미 has_named_content에서 확인됨
        return True
    if words and words.issubset(GENERIC_NOUN_ONLY):
        return True
    return False


def source_sentence_for_summary(detail: str, domain: str) -> str:
    """
    B 규칙: detail(소스 원문)이 충분히 구체적이면 압축하지 않고 그대로 활용.
    반환값이 비어있으면 기존 target 압축 방식 사용.
    """
    if not detail:
        return ""
    t = clean_line(detail)
    # 너무 짧거나 너무 길면 사용 안 함
    if len(t) < 8 or len(t) > 120:
        return ""
    # 고유명사 없으면 사용 안 함
    if not has_named_content(t):
        return ""
    # 노이즈 패턴이면 사용 안 함
    if TABLE_TARGET_PATTERN.search(t):
        return ""
    if re.search(r"(바로가기|공지|https?://|클릭하여|참고해\s*주세요)", t):
        return ""
    # 문장 끝 정리 (명사형으로)
    t = re.sub(r"\s*(됩니다|합니다|입니다|ㅂ니다|었습니다|겠습니다)\s*\.?\s*$", "", t)
    t = re.sub(r"\s*\.\s*$", "", t).strip()
    return t


def clean_line(line: str) -> str:
    line = compact_text(line)
    line = re.sub(r"^[.。]\s*", "", line)
    line = re.sub(r"^[•·ㆍ■●◦≫▶▷\-*]+\s*", "", line)
    line = re.sub(r"^\(?\d{1,2}\)?[.)]\s*", "", line)
    return line.strip()


def is_generic_representative_title(title: str) -> bool:
    t = clean_line(title)
    return re.search(
        r"(신규\s*(?:콘텐츠|content)|추가\s*및\s*변경|신규\s*추가|주요\s*안내|주요\s*업데이트)",
        t,
        re.I,
    ) is not None


def representative_detail_target(detail: str) -> str:
    t = clean_line(detail)
    t = re.sub(r"\s*(?:이|가)\s*(?:아래와|다음과)?\s*같이\s*변경됩니다\.?$", "", t)
    t = re.sub(r"\s*(?:이|가)\s*(?:아래와|다음과)?\s*같\s*$", "", t)
    t = re.sub(r"\s*(?:이|가)\s*(?:새롭게\s*)?추가됩니다\.?$", "", t)
    t = re.sub(r"\s*(?:이|가)\s*추가됩니다\.?$", "", t)
    t = re.sub(r"\s*추가됩니다\.?$", "", t)
    t = re.sub(r"\s*변경됩니다\.?$", "", t)
    t = re.sub(r"\s*리뉴얼됩니다\.?$", "", t)
    t = re.sub(r"\s*확장됩니다\.?$", "", t)
    t = re.sub(r"\s*돌아옵니다\.?$", "", t)
    t = re.sub(r"\s*해제됩니다\.?$", "", t)
    t = re.sub(r"\s*상향\s*조정됩니다\.?$", "", t)
    t = re.sub(r"\s*하향\s*조정됩니다\.?$", "", t)
    t = re.sub(r"\s*조정됩니다\.?$", "", t)
    t = re.sub(r"\s*개선됩니다\.?$", "", t)
    t = re.sub(r"\s*시작됩니다\.?$", "", t)
    return t.strip(" .")


def is_representative_detail_line(line: str) -> bool:
    t = clean_line(line)
    if not t or is_table_or_link_line(t) or TABLE_TARGET_PATTERN.search(t):
        return False
    if re.search(r"(바로가기|공지|URL|https?://|자세한\s*내용|참고해\s*주세요)", t, re.I):
        return False
    if re.match(r"^[◦※*]|이벤트\s*기간|^예시\d*$", t):
        return False
    return True


def is_bullet_line(line: str) -> bool:
    return re.match(r"^\s*[\-•·ㆍ■●◦*]\s*", str(line or "")) is not None


def is_table_or_link_line(line: str) -> bool:
    t = clean_line(line)
    if not t:
        return True
    if re.match(r"^\[.+\]$", t):
        return True
    if t in {"분류", "기존", "변경", "단계", "진행 일정", "화요일 경기", "토요일 경기"}:
        return True
    if re.match(r"^\d{1,3}(,\d{3})*(\s*~\s*\d{1,3}(,\d{3})*)?$", t):
        return True
    return False


def is_heading_like(line: str) -> bool:
    t = clean_line(line)
    if not t or t.endswith((".", "다.", "니다.", "다")):
        return False
    if len(t) > 32:
        return False
    if re.match(r"^\d{1,2}\s*월\s*\d{1,2}\s*일|^\d{1,2}/\d{1,2}|^\d{4}년", t):
        return False
    if re.search(r"(\d{1,2}:\d{2}|~|종료\s*시|변경\s*내용|추가\s*사항)", t):
        return False
    if t in {"변경 및 추가", "추가 및 변경"}:
        return False
    if re.search(r"(사용하여|활용한|유발|증가|감소|피해|대상|확률|재사용|유지)", t):
        return False
    return re.search(r"(추가|변경|조정|개선|개편|시작|종료|밸런스|balance|class change|클래스\s*체인지|크루세이드|시즌|기능)", t, re.I) is not None


def balance_target_line(line: str) -> str:
    t = clean_line(line)
    if not t:
        return ""
    m = re.match(r"^(.+?)\s*[:：]", t)
    if m:
        t = clean_line(m.group(1))
    if re.search(r"(밸런스|balance|기술\s*효과|특성|변경|추가|등급|기술명|레벨)", t, re.I):
        return ""
    if len(t) > 20:
        return ""
    if re.search(r"[\d%~→]", t):
        return ""
    if t in {"희귀", "영웅", "전설", "일반", "고급", "등급", "기술명"}:
        return ""
    if re.search(r"(단검|지팡이|궁수|전사|마법사|레이피어|sword|dagger|staff|wand|class)", t, re.I):
        return t
    return ""


def split_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = compact_text(raw)
        if not line:
            continue
        if line in {"|", "-", " "}:
            continue
        out.append(line)
    return out


def quoted(text: str) -> str:
    patterns = [
        r"[‘’'\"<\[]([^'‘’\"<>\[\]]{2,80})[‘’'\">\]]",
        r"‘([^’]{2,80})’",
        r"“([^”]{2,80})”",
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "")
        if m:
            return compact_text(m.group(1))
    return ""


def normalize_target(target: str) -> str:
    target = compact_text(target)
    target = target.strip(" .。")
    target = re.sub(r"^(?:A|An)\s+new\s+", "", target, flags=re.I).strip()
    target = re.sub(r"^(New|new|신규)\s+", "", target).strip()
    target = re.sub(r"\s+(will\s+(?:be\s+)?(?:added|adjusted|commence|begin|improved|changed|updated|introduced))\.?$", "", target, flags=re.I)
    target = re.sub(r"\s+(added|introduced|adjusted|improved|changed|updated|commenced|began|started|ended|closed|opened)\.?$", "", target, flags=re.I)
    target = re.sub(r"\s*(?:현상이\s*)?수정됩니다\.?$", "", target)
    target = re.sub(rf"\s+(?:{CHANGE_SUFFIXES})$", "", target)
    target = re.sub(r"\s*(이|가|을|를|은|는)\s*$", "", target)
    return target.strip(" :-")


def strip_change_suffix(target: str) -> str:
    target = compact_text(target).strip(" .。")
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
        return f"신규 이벤트 {m.group(1)}종", CHANGE_WORDS["add"], ["NORMALIZED_EVENT_COUNT"]
    if key in {"events", "event", "newevents"}:
        return "신규 이벤트", CHANGE_WORDS["run"], ["NORMALIZED_GENERIC_EVENT"]
    if key in {"eventupdates", "updates"}:
        return "이벤트", CHANGE_WORDS["renew"], ["NORMALIZED_EVENT_UPDATE"]
    return target, change, []


def normalize_server_target(target: str, source: str, change: str) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    q = quoted(source)
    if q:
        target = q
    source_key = norm_key(source)
    if not target or norm_key(target) in {norm_key("서버"), "server", "world"}:
        if "신규서버" in source_key or "newserver" in source_key:
            target = "신규 서버"
            flags.append("NORMALIZED_GENERIC_SERVER")
        else:
            target = "서버"
    elif re.match(r"^서버\s+\S+", target) and "서버 이전" not in target:
        m = re.match(r"^서버\s+(.+)$", target)
        target = f"{m.group(1)} 서버" if m else target
        flags.append("NORMALIZED_SERVER_NAME")
    elif not re.search(r"(서버|월드|server|world)", target, re.I):
        target = f"{target} 서버"
        flags.append("NORMALIZED_SERVER_NAME")
    return target, change, flags


def normalize_bug_target(target: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    target = re.sub(r"\s*(?:현상이\s*)?수정됩니다\.?$", "", target)
    target = re.sub(r"\s*(?:갱신|표시|적용|노출|작동|진행|획득|반영)되지\s*않(?:는)?$", "", target)
    target = re.sub(r"\s*(?:되지|지)\s*않$", "", target)
    target = re.sub(r"\s*(이|가|을|를|은|는)\s*$", "", target).strip()
    if target and "오류" not in target:
        target = f"{target} 오류"
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
    if re.search(r"시즌\s*\d+.*종료.*\d+.*시작", source) and "신규 시즌" in title:
        target = clean_line(title)
        change = CHANGE_WORDS["start"]
        flags.append("NORMALIZED_SEASON_ROLLOVER")
    if domain == KO["event"]:
        target, change, added = normalize_event_target(target, source, change)
        flags.extend(added)
    if domain == KO["server"]:
        if re.search(r"(서버\s*이전|이전\s*서버|server transfer)", source, re.I):
            target = "서버 이전"
            change = CHANGE_WORDS["run"]
            flags.append("NORMALIZED_SERVER_TRANSFER")
        target, change, added = normalize_server_target(target, source, change)
        flags.extend(added)
    if domain == KO["shop"]:
        key = norm_key(target)
        if key in {"seasonpass", norm_key("시즌 패스")}:
            target = "Season Pass" if re.search(r"season\s*pass", source, re.I) else "시즌 패스"
            flags.append("NORMALIZED_SHOP_TARGET")
        elif key in {norm_key("상품"), "product"} and change == CHANGE_WORDS["add"]:
            target = "신규 상품"
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
    if len(target) > 120:
        flags.append("OVERLONG_TARGET")
    # A 규칙: 고유명사 없이 generic 명사만으로 구성된 target
    if is_vague_target(target) and not has_named_content(sentence):
        flags.append("VAGUE_TARGET")
    return flags


def change_type(text: str) -> str:
    low = str(text or "").lower()
    compact = norm_key(text)
    if re.search(r"\b(end|ended|expires?|closed?)\b", low) or "종료" in compact:
        return CHANGE_WORDS["end"]
    if any(x in low for x in ["commence", "begin", "start", "open"]) or "시작" in compact or "돌아옵니다" in compact:
        return CHANGE_WORDS["start"]
    if any(x in low for x in ["improved", "improvement"]) or "개선" in compact:
        return CHANGE_WORDS["improve"]
    if "하향" in compact or "decreased" in low:
        return CHANGE_WORDS["nerf"]
    if "상향" in compact or "increased" in low:
        return CHANGE_WORDS["buff"]
    if "확장" in compact or "expanded" in low:
        return CHANGE_WORDS["expand"]
    if any(x in low for x in ["adjusted", "adjustment"]) or "조정" in compact:
        return CHANGE_WORDS["adjust"]
    if re.search(r"\b(changed|change)\b", low) or "변경" in compact or "해제" in compact:
        return CHANGE_WORDS["change"]
    if any(x in low for x in ["renewed", "updated", "renewal"]) or "갱신" in compact or "리뉴얼" in compact:
        return CHANGE_WORDS["renew"]
    if any(x in low for x in ["fixed", "fix"]) or "수정" in compact:
        return CHANGE_WORDS["fix"]
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
        if re.search(r"(밸런스|balance)", cleaned, re.I):
            continue
        if len(cleaned) <= 20 and not re.search(r"[추가조정변경수정]", cleaned):
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

    if re.search(r"(밸런스|balance)", text, re.I):
        domain = KO["class_balance"] if re.search(r"(클래스|직업|class)", text, re.I) else KO["skill_balance"]
        return domain, CHANGE_WORDS["adjust"], ["class_balance"]
    if re.search(r"(일부\s*클래스\s*변경|클래스\s*케어|클래스\s*기술\s*및\s*특성\s*효과)", text, re.I):
        return KO["class_balance"], CHANGE_WORDS["adjust"], ["class_balance"]

    if re.search(r"(new class|new combat class|신규\s*(클래스|직업))", text, re.I):
        return KO["new_class"], CHANGE_WORDS["add"], ["new_class"]
    if re.search(r"(class change|클래스\s*체인지|직업\s*변경)", text, re.I):
        return KO["class_change"], change_type(text), ["class_change"]
    if re.search(r"(new system|신규\s*시스템|creed|potential)", text, re.I):
        return KO["new_system"], change_type(text), ["new_system"]
    if re.search(r"(new region|신규\s*지역)", text, re.I):
        return KO["new_region"], CHANGE_WORDS["add"], ["new_region"]
    if re.search(r"(server transfer|server merge|서버\s*이전|서버\s*통합)", text, re.I):
        sig = "server_transfer" if re.search(r"(transfer|이전)", text, re.I) else "server_merge"
        return KO["server"], change_type(text), [sig]
    if re.search(r"(new server|server\s+(?:added|opened|closed)|growth server|boost(?:ing)? world|신규\s*서버|서버\s*(?:추가|종료|오픈|개설)|성장\s*서버|시즌\s*서버)", text, re.I):
        if re.search(r"(closed|종료)", text, re.I):
            sig = "server_closed"
        elif re.search(r"(new|added|opened|신규|추가|오픈|개설)", text, re.I):
            sig = "new_server"
        else:
            sig = "server_change"
        return KO["server"], change_type(text), [sig]
    if re.search(r"(world battlefront|battlefront|crusade|크루세이드|영지)", text, re.I):
        sig = "new_world_content" if re.search(r"(new|신규|추가)", text, re.I) else "world_content"
        return KO["world"], change_type(text), [sig]
    if re.search(r"(dominion|도미니언|점령전|공성전|길드\s*단위|길드\s*전장|전쟁|전장|점령)", text, re.I):
        sig = "new_pvp_war" if re.search(r"(new|신규|추가)", text, re.I) else "pvp_war"
        return KO["pvp"], change_type(text), [sig]
    if re.search(r"(dungeon|boss|raid|monster|지하감옥|던전|보스|몬스터|필드)", text, re.I):
        if re.search(r"(체력|데미지|난이도|하향|difficulty|damage)", text, re.I):
            return KO["pve_balance"], change_type(text), ["pve_balance"]
        sig = "new_pve_content" if re.search(r"(new|신규|새롭게|추가)", text, re.I) else "pve_content"
        return KO["pve"], change_type(text), [sig]
    if re.search(r"(item collection|아이템\s*수집|수집)", text, re.I):
        return KO["collection"], change_type(text), ["collection"]
    if re.search(r"(spirit|정령)", text, re.I):
        return KO["spirit"], change_type(text), ["spirit"]
    if re.search(r"(artifact|inner armor|weapon style|equipment|gear|mount|glider|accessory|lamp|장비|장신구|탈것|글라이더|무기\s*외형|밤까마귀)", text, re.I):
        return KO["equipment"], change_type(text), ["equipment"]
    if re.search(r"(shop|pass|product|purchase|merchant|package|cash shop|상점|패스|상품|패키지|구매|판매|소환권|캐시샵)", text, re.I):
        return KO["shop"], change_type(text), ["shop"]
    if re.search(r"(event|check-in|attendance|이벤트|출석|미션)", text, re.I):
        change = CHANGE_WORDS["run"] if re.search(r"(이벤트)", text, re.I) else change_type(text)
        return KO["event"], change, ["event"]
    if re.search(r"(\bui\b|convenience|display|image|이미지|편의|표시|절전모드)", text, re.I):
        return KO["ui"], change_type(text), ["ui"]
    if re.search(r"(schedule|일정)", text, re.I):
        return KO["schedule"], change_type(text), ["schedule"]
    if re.search(r"(bug|issue|fix|버그|오류|현상)", text, re.I):
        return KO["bug"], CHANGE_WORDS["fix"], ["bug_fix"]
    return KO["system_growth"], change_type(text), ["system_growth"]


def target_from_unit(title: str, detail: str, domain: str, game: str = "") -> str:
    if domain in {KO["class_balance"], KO["skill_balance"]}:
        targets = balance_targets(title, detail)
        return ", ".join(targets) if targets else clean_line(title)

    text = clean_line(title)
    if detail and (is_generic_representative_title(text) or game == "NightCrows_KR"):
        detail_target = representative_detail_target(detail)
        if detail_target:
            return normalize_target(detail_target)
    if domain == KO["new_class"]:
        q = quoted(detail) or quoted(text)
        return normalize_target(q or text)
    if domain == KO["event"]:
        m = re.search(r"(신규\s*이벤트)", text)
        if m:
            return m.group(1)
    if domain == KO["shop"]:
        m = re.search(r"(신규\s*(?:상품|패키지))", text)
        if m:
            return m.group(1)
    if domain == KO["server"]:
        q = quoted(detail) or quoted(text)
        if q:
            return normalize_target(q)
    if domain == KO["pve_balance"] or (re.search(r"\(.+\)", text) and not re.search(r"\)\s+(추가|개편|개선|조정|변경|시작|종료|진행)", text)):
        return normalize_target(text)
    if re.search(r"^(기타\s*)?(개선|변경)\s*사항$", text) and clean_line(detail):
        return normalize_target(clean_line(detail))
    if domain == KO["class_change"]:
        return normalize_target(text)
    patterns = [
        r"^(?:New|new)\s+[^:]{2,30}:\s*(.+)$",
        r"^(.+?)\s+will\s+(?:be\s+)?(?:added|adjusted|improved|changed|commence|begin|introduced|updated)",
        r"^(.+?)\s+(?:added|introduced|adjusted|improved|changed|updated|commenced|started|ended|closed|opened)\.?$",
        r"^(.+?)\s+(?:추가|개편|개선|조정|변경|시작|종료|진행)",
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
    target = target_from_unit(title, detail, domain, game)
    if domain in {KO["class_balance"], KO["skill_balance"]} and not target:
        target = clean_line(title)
    target, change, normalization_flags = normalize_target_change(domain, target, change, title, detail)

    # B 규칙: target이 vague하고 detail에 구체적 소스 문장이 있으면 그대로 활용
    used_source_sentence = False
    source_sent = source_sentence_for_summary(detail, domain)
    if source_sent and is_vague_target(target):
        sentence = f"{domain}: {source_sent}"
        normalization_flags.append("SOURCE_SENTENCE_USED")
        used_source_sentence = True
    else:
        sentence = f"{domain}: {target} {change}".strip()

    quality_flags = quality_flags_for_summary(sentence, domain, target, change)

    # B 규칙으로 소스 문장을 살렸으면 VAGUE_TARGET 플래그 제거 (드롭하지 않음)
    if used_source_sentence and "VAGUE_TARGET" in quality_flags:
        quality_flags.remove("VAGUE_TARGET")

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
        if re.search(r"^[\[◇◆■●◈\s]*(?:In-Game Updates|Main Updates|Update Summary)[\]◇◆■●◈\s]*$", line, re.I):
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
        if re.search(r"(패치\s*노트\s*\]|\bPatch Note Details\b|\bUpdate Details\b|^■)", cleaned, re.I):
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
            numbered = clean_line(m.group(2))
            return "" if TABLE_TARGET_PATTERN.search(numbered) else numbered
        cleaned = clean_line(line)
        if TABLE_TARGET_PATTERN.search(cleaned):
            return ""
        if 3 <= len(cleaned) <= 80 and is_heading_like(line) and not is_bullet_line(line) and not is_table_or_link_line(line):
            if re.search(r"(추가|변경|조정|개선|개편|시작|종료|밸런스|balance|클래스\s*체인지|시즌|기능)", cleaned, re.I):
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
        is_balance = re.search(r"(밸런스|balance|일부\s*클래스\s*변경|클래스\s*케어)", title, re.I) is not None
        while j < n:
            nxt = section[j]
            if title_at(j):
                break
            cleaned_nxt = clean_line(nxt)
            if not is_balance and not is_bullet_line(nxt) and cleaned_nxt and (
                TABLE_TARGET_PATTERN.search(cleaned_nxt)
                or (3 <= len(cleaned_nxt) <= 80 and is_heading_like(nxt))
            ):
                break
            if is_bullet_line(nxt):
                if is_balance:
                    if not is_table_or_link_line(nxt):
                        details.append(nxt)
                elif is_representative_detail_line(nxt):
                    details.append(nxt)
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
        if "【" in line and re.search(r"업데이트\s*상세\s*내역\s*안내", line):
            start = i + 1
    if start < 0:
        for i, line in enumerate(lines):
            if re.search(r"아래를\s*참고|업데이트에\s*대한\s*자세한", line):
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
        if t in {"기타 변경 사항", "변경 사항"}:
            return True
        if re.search(r"(판매\s*탭|상품명|구성품|구매\s*제한|아이템\s*명|수집\s*효과)", t):
            return True
        return False

    def choose_titles(section_title: str, children: list[str]) -> list[str]:
        title = clean_line(section_title)
        children = [clean_line(x) for x in children if clean_line(x) and not is_noise(x)]
        if not title:
            return children[:3]
        if re.search(r"(기타|변경)", title) and children:
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
        if re.search(r"(추가\s*안내\s*사항|감사합니다|^다음검색$|^댓글$)", line):
            break
        if re.match(r"^[Ⅰ-Ⅻ]+$", line) or re.match(r"^[Ⅰ-Ⅻ]+\s*\.", line):
            flush()
            j = i + 1
            while j < len(lines) and clean_line(lines[j]) in {"", ".", "·"}:
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
        if re.search(r"자세한\s*사항|아래\s*내용|하단의\s*내용", line):
            start = i + 1
            break

    units: list[dict[str, Any]] = []
    current_section = ""
    section_emitted = False
    section_pattern = re.compile(
        r"(신규|추가|개선|변경|오류|수정|이벤트|연합|밸런스|콘텐츠|던전|몬스터|장비|클래스|시즌)"
    )

    def next_detail(idx: int) -> str:
        for nxt in lines[idx + 1 : min(len(lines), idx + 5)]:
            cleaned = clean_line(nxt)
            if not cleaned or is_table_or_link_line(cleaned):
                continue
            if is_bullet_line(nxt):
                cleaned = clean_line(nxt)
            if re.match(r"^[■※*]|이벤트\s*기간|^예시\d*$", cleaned):
                continue
            return cleaned
        return ""

    i = start
    while i < len(lines) and len(units) < 16:
        raw = lines[i]
        line = clean_line(raw)
        if re.search(r"(즐겨찾기|공유하기|회사소개|이용약관|^목록$)", line):
            break
        if not line:
            i += 1
            continue
        if not is_bullet_line(raw) and 2 <= len(line) <= 42 and section_pattern.search(line):
            current_section = line
            section_emitted = False
            if re.search(r"(신규\s*콘텐츠|신규\s*몬스터|연합|클래스\s*밸런스)", line):
                detail = next_detail(i)
                units.append(build_summary_unit(game, line, detail, len(units) + 1))
                section_emitted = True
            i += 1
            continue
        if is_bullet_line(raw):
            if re.match(r"^[•·ㆍ■●\-*]*\s*[※＊■]", raw):
                i += 1
                continue
            m = re.match(r"^[•·ㆍ■●\-*]*\s*\[([^\]]{1,20})\]", raw)
            if m:
                category = m.group(1)
                detail = next_detail(i)
                title = " ".join(x for x in [current_section, category, detail] if x)
                if detail and title and not is_table_or_link_line(title):
                    units.append(build_summary_unit(game, title, detail, len(units) + 1))
            elif current_section and not section_emitted and re.search(r"(신규|추가|개선|변경|오류|수정|이벤트|연합|밸런스|콘텐츠|던전|몬스터|장비|클래스)", current_section):
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
        if capture and re.search(r"(자세한\s*사항|자세한\s*내용|하단의\s*내용|아래\s*내용)", cleaned):
            break
        if capture and cleaned:
            intro.append(cleaned)
    text = compact_text(" ".join(intro))
    if not text:
        return []
    parts = re.split(r"(?:\.\s+|\s*,\s*|\s+더불어\s+|\s+이와\s*함께\s+)", text)
    units: list[dict[str, Any]] = []
    for part in parts:
        clause = clean_line(part)
        clause = re.sub(r"^(?:이번\s*)?업데이트(?:를|에서는|를\s*통해)?\s*", "", clause)
        clause = re.sub(r"^(?:이번\s*)?임시\s*점검에서는\s*", "", clause)
        clause = re.sub(r"^통해\s*", "", clause)
        clause = re.sub(r"^(?:또한|,|과|,?\s*이와\s*함께)\s*", "", clause)
        if re.search(r"(안내드립니다|참고해주시기|확인해\s*주시기)", clause):
            continue
        if len(clause) < 8:
            continue
        if not re.search(r"(추가|조정|개선|변경|수정|진행|적용|상향|하향|시작|종료|확장)", clause):
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
        section = find_section(lines, [r"^\[?\s*주요\s*업데이트\s*사항\s*\]?$"], [r"^\[.+패치\s*노트.*\]$", r"^■", r"^\[?\s*상세"])
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
                r"주요\s*안내\s*사항",
                r"주요\s*업데이트",
                r"신규\s*추가\s*및\s*변경\s*사항",
                r"신규\s*콘텐츠\s*추가\s*및\s*변경\s*사항",
                r"업데이트\s*상세\s*내역",
            ],
            [
                r"^Ⅱ\.",
                r"^Ⅲ\.",
                r"^Ⅳ\.",
                r"^신규\s*이벤트$",
                r"상세\s*안내",
                r"업데이트\s*상세",
                r"패치\s*노트\s*상세",
                r"이벤트\s*안내",
                r"상품\s*안내",
                r"오류\s*수정",
                r"^개선\s*사항$",
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
            if re.search(r"(:\s*(?:＊|※|\(?추가\)?|\(?변경\)?|지역명)|종료\s*이벤트|기타\s*변경|시즌\s*패스)", line)
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
        "card_summary": " · ".join(tags[:4]),
        "units": units,
        "signals": signals,
        "quality_status": "PASS" if body and not flags else "REVIEW",
        "flags": flags,
        "quality_warnings": dropped_quality_flags,
    }


def major_from_signals(signals: list[str]) -> bool:
    return any(signal in MAJOR_SIGNALS for signal in signals or [])
