from __future__ import annotations
"""
source_section_extractors_v2.py
REWRITE_PLAN.md (2026-06-08) 기준 전면 재작성.
- body_summary 형식: "'현신도'가 추가됩니다." (완전한 문장)
- find_section / classify_unit 재사용
- 진입점: extract_units() / section_summary_preview()
버그 수정 (2026-06-08):
  이슈1: _EXCLUDE_B 불완전 헤딩 패턴 추가
  이슈2: _is_heading_b 과거형(었/였습니다) 제외
  이슈3: josa_i_ga 후치조사 strip
  이슈4: _is_heading_b 완결문장 제외
"""

import re
from typing import Any

KO = {
    "new_class":     "신규 클래스",
    "class_change":  "클래스/전직",
    "class_balance": "클래스 밸런스",
    "skill_balance": "스킬 밸런스",
    "new_system":    "신규 시스템",
    "system_growth": "시스템/성장",
    "new_region":    "신규 지역",
    "pve":           "PvE 콘텐츠",
    "pve_balance":   "PvE 밸런스",
    "pvp":           "PvP/전쟁",
    "world":         "월드 콘텐츠",
    "server":        "서버/월드",
    "equipment":     "성장/장비",
    "collection":    "성장/수집",
    "spirit":        "성장/정령",
    "event":         "이벤트/보상",
    "shop":          "상점/BM",
    "ui":            "편의/UI",
    "schedule":      "일정",
    "bug":           "버그 수정",
}

CHANGE_WORDS = {
    "add": "추가", "rework": "개편", "improve": "개선",
    "adjust": "조정", "change": "변경", "start": "시작",
    "end": "종료", "expand": "확장", "support": "지원",
    "renew": "갱신", "nerf": "하향", "buff": "상향",
    "fix": "수정", "run": "진행", "open": "오픈",
    "delete": "삭제", "reset": "초기화", "apply": "적용",
}

VERB_TABLE = {
    "추가":  "추가됩니다",
    "변경":  "변경됩니다",
    "개선":  "개선됩니다",
    "조정":  "조정됩니다",
    "확장":  "확장됩니다",
    "시작":  "시작됩니다",
    "종료":  "종료됩니다",
    "오픈":  "오픈됩니다",
    "진행":  "진행됩니다",
    "적용":  "적용됩니다",
    "초기화": "초기화됩니다",
    "삭제":  "삭제됩니다",
    "갱신":  "갱신됩니다",
    "수정":  "수정됩니다",
    "하향":  "하향 조정됩니다",
    "상향":  "상향 조정됩니다",
    "개편":  "개편됩니다",
    "지원":  "지원됩니다",
}

SECTION_START_PATTERNS = [
    r"주요\s*업데이트\s*사항",
    r"update\s*summary",
    r"main\s*updates",
    r"주요\s*내용",
    r"업데이트\s*요약",
]
SECTION_END_PATTERNS = [
    r"상세\s*내용",
    r"세부\s*내용",
    r"\bdetail",
    r"패치\s*상세",
    r"patch\s*note\s*details",
    r"update\s*details",
    r"known\s*issues",
    r"resolved\s*issues",
]

_B_PRIORITY = [
    (1, re.compile(r"(신규|새로운).{0,12}(콘텐츠|지역|던전|시스템|서버|필드|클래스|아티팩트)", re.I)),
    (2, re.compile(r"(클래스|장비|스킬|무기|방어구).{0,15}(추가|변경|조정|개선|밸런스)", re.I)),
    (3, re.compile(r"(시젠|서버|월드).{0,12}(시작|종료|이전|변경|오픈)", re.I)),
    (4, re.compile(r"이벤트.{0,20}(진행|추가|시작|오픈)", re.I)),
    (5, re.compile(r"(개선|수정|조정|변경).{0,10}(됩니다|사항|적용)", re.I)),
]

_NOISE_LINE = re.compile(
    r"(바로가기|공지|https?://|자세한\s*내용"
    r"|참고해\s*주세요|클릭하여"
    r"|이용약관|공유하기|회사소개|^목록$|감사합니다)",
    re.I,
)
_SKIP_HDR = re.compile(
    r"^\[?\s*(?:In-Game Updates|Main Updates|Update Summary"
    r"|주요\s*업데이트\s*사항)\s*\]?\s*$",
    re.I,
)

_EN_VERB_MAP = {
    "added": "추가", "introduced": "추가",
    "commence": "시작", "commenced": "시작",
    "begin": "시작", "begins": "시작", "started": "시작",
    "ended": "종료", "closed": "종료",
    "opened": "오픈",
    "adjusted": "조정",
    "improved": "개선",
    "changed": "변경", "updated": "변경",
    "removed": "삭제", "deleted": "삭제",
    "ends": "종료", "reworked": "개편",
}

_KO_NOUN_VERB = [
    ("하향 조정", "하향"),
    ("상향 조정", "상향"),
    ("판매 종료", "종료"),
    ("판매 시작", "시작"),
    ("추가", "추가"), ("변경", "변경"),
    ("개선", "개선"), ("개편", "개편"),
    ("조정", "조정"), ("확장", "확장"),
    ("시작", "시작"), ("종료", "종료"),
    ("오픈", "오픈"), ("진행", "진행"),
    ("적용", "적용"), ("초기화", "초기화"),
    ("삭제", "삭제"), ("제거", "삭제"),
    ("갱신", "갱신"), ("수정", "수정"),
    ("리뉴얼", "개편"),
]

_KO_SENT_VERB = re.compile(
    r"(?P<target>.+?)(?:이|가|을|를|은|는)?\s*"
    r"(?P<verb>추가|변경|개선|개편|조정|확장"
    r"|시작|종료|오픈|진행|적용|초기화"
    r"|삭제|갱신|수정|하향\s*조정|상향\s*조정"
    r"|판매가\s*시작|판매가\s*종료)"
    r"됩니다\.?\s*$"
)

_LOW_VALUE = {
    "events", "event", "eventupdates", "newevents", "updates", "mainupdates",
}


def compact_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_key(text):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").lower())


def clean_line(line):
    line = compact_text(line)
    line = re.sub(r"^[.。]\s*", "", line)
    line = re.sub(r"^[•·ㅣ■●◦≫▶▷\-*＊※]+\s*", "", line)  # 이슈: ＊ 등 추가
    line = re.sub(r"^\(?\d{1,2}\)?[.)]\s*", "", line)
    # 이슈: (추가)/(변경) 등 변경유형 괄호 prefix 제거
    line = re.sub(r"^\((?:추가|변경|개선|수정|조정|확장|삭제|오픈|진행|하향|상향|개편|적용|초기화|갱신)\)\s*", "", line)
    return line.strip()


def split_lines(text):
    out = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = compact_text(raw)
        if not line or line in {"|", "-", " "}:
            continue
        out.append(line)
    return out


def is_bullet_line(line):
    return re.match(r"^\s*[\-•·ㅣ■●◦*]\s*", str(line or "")) is not None


def change_type(text):
    low = str(text or "").lower()
    c = norm_key(text)
    if re.search(r"\b(end|ended|expires?|closed?)\b", low) or "종료" in c:
        return CHANGE_WORDS["end"]
    if any(x in low for x in ["commence", "begin", "start", "open"]) or "시작" in c or "오픈" in c:
        return CHANGE_WORDS["start"]
    if any(x in low for x in ["improved", "improvement"]) or "개선" in c:
        return CHANGE_WORDS["improve"]
    if "하향" in c or "decreased" in low:
        return CHANGE_WORDS["nerf"]
    if "상향" in c or "increased" in low:
        return CHANGE_WORDS["buff"]
    if "확장" in c or "expanded" in low:
        return CHANGE_WORDS["expand"]
    if any(x in low for x in ["adjusted", "adjustment"]) or "조정" in c:
        return CHANGE_WORDS["adjust"]
    if re.search(r"\b(changed|change)\b", low) or "변경" in c or "해제" in c:
        return CHANGE_WORDS["change"]
    if any(x in low for x in ["renewed", "updated", "renewal"]) or "갱신" in c or "리뉴얼" in c:
        return CHANGE_WORDS["renew"]
    if any(x in low for x in ["fixed", "fix"]) or "수정" in c:
        return CHANGE_WORDS["fix"]
    if "진행" in c:
        return CHANGE_WORDS["run"]
    if "초기화" in c:
        return CHANGE_WORDS["reset"]
    if "삭제" in c or "제거" in c:
        return CHANGE_WORDS["delete"]
    if "적용" in c:
        return CHANGE_WORDS["apply"]
    return CHANGE_WORDS["add"]


def classify_unit(title, detail):
    text = f"{title} {detail}"
    c = norm_key(text)
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
    if re.search(r"(new server|신규\s*서버|서버.{0,8}(?:추가|종료|오픈|개설)|성장\s*서버|시젠\s*서버)", text, re.I):
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
    if re.search(r"(dungeon|boss|raid|monster|던전|보스|몬스터|필드)", text, re.I):
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
        ch = CHANGE_WORDS["run"] if re.search(r"(이벤트)", text, re.I) else change_type(text)
        return KO["event"], ch, ["event"]
    if re.search(r"(\bui\b|convenience|display|image|이미지|편의|표시|절전모드)", text, re.I):
        return KO["ui"], change_type(text), ["ui"]
    if re.search(r"(schedule|일정)", text, re.I):
        return KO["schedule"], change_type(text), ["schedule"]
    if re.search(r"(bug|issue|fix|버그|오류|현상)", text, re.I):
        return KO["bug"], CHANGE_WORDS["fix"], ["bug_fix"]
    return KO["system_growth"], change_type(text), ["system_growth"]


def find_section(lines, start_patterns, end_patterns, max_lines=220):
    start = -1
    for i, line in enumerate(lines):
        if any(re.search(p, line, re.I) for p in start_patterns):
            start = i + 1
            break
    if start < 0:
        return []
    out = []
    for line in lines[start:]:
        if out and any(re.search(p, line, re.I) for p in end_patterns):
            break
        out.append(line)
        if len(out) > max_lines:
            break
    return out


def normalize_quotes(text):
    q = "'"
    text = re.sub(r'["""]([^"""]{2,80})["""]', q + r'\1' + q, text)
    text = re.sub(r'[「『【](.{2,80})[」』】]', q + r'\1' + q, text)
    return text


def ensure_quotes(text):
    return normalize_quotes(text)


_STRIP_JOSA = re.compile(r'[은는]$')  # 이슈3 수정: 은/는만 제거, 이/가/의 등 단어 일부로 오인 방지


def josa_i_ga(word):
    if not word:
        return "이"
    s = re.sub(r"['‘’“”)]+$", "", word)
    s = _STRIP_JOSA.sub('', s)
    last = s[-1] if s else word[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return "이" if (code - 0xAC00) % 28 != 0 else "가"
    return "이"


def format_final_sentence(target, change_verb):
    if not target or not change_verb:
        return ""
    target = target.strip(" .")
    target = re.sub(r'[은는]$', '', target)  # 이슈3 수정: target 자체의 후치 조사 제거
    if not target:
        return ""
    target = ensure_quotes(target)
    particle = josa_i_ga(target)
    return target + particle + " " + change_verb + "."


def _verb_key_to_final(change):
    return VERB_TABLE.get(change, change + "됩니다")


def _parse_a_line(line):
    t = clean_line(line)
    if not t or len(t) < 4 or _NOISE_LINE.search(t):
        return None
    if re.search(r"(Patch Note Details|Update Details|Known Issues|패치\s*노트\s*상세)", t, re.I):
        return None
    # 이슈2: 과거형/완결 문장은 heading 아님
    if re.search(r'(?:었|였|겠)[습됩집합입]니다\.?\s*$', t):
        return None
    m = _KO_SENT_VERB.match(t)
    if m:
        tgt = m.group("target").strip()
        verb_raw = re.sub(r"\s+", "", m.group("verb"))
        for kp, ck in _KO_NOUN_VERB:
            if norm_key(verb_raw) == norm_key(kp):
                return tgt, ck
        return tgt, "추가"
    me = re.match(r"^(.+?)\s+(?:will\s+(?:be\s+)?)?(\w+)\.?\s*$", t, re.I)
    if me and me.group(2).lower() in _EN_VERB_MAP:
        return me.group(1).strip(), _EN_VERB_MAP[me.group(2).lower()]
    for kp, ck in _KO_NOUN_VERB:
        m2 = re.match(r"^(.+?)\s+" + re.escape(kp) + r"\s*$", t)
        if m2:
            return m2.group(1).strip(), ck
    if 4 <= len(t) <= 100 and not re.match(r"^[\[\]#<［]", t):
        inferred = change_type(t)
        t = re.sub(r"\s+(?:안내|예정|사항)\s*$", "", t).strip()
        for kp, _ in _KO_NOUN_VERB:
            t = re.sub(r"\s+" + re.escape(kp) + r"\s*$", "", t).strip()
        return t, inferred
    return None


def extract_section_a(game, section):
    units = []
    current_title = ""
    details = []

    def flush():
        nonlocal current_title, details
        if not current_title:
            return
        detail_str = " ".join(clean_line(x) for x in details[:2] if clean_line(x))
        parsed = _parse_a_line(current_title)
        if parsed:
            target, ck = parsed
            if len(target) < 4 and detail_str:
                target = clean_line(detail_str)
        else:
            target = clean_line(current_title)
            ck = change_type(current_title)
            # 이슈2: parse 실패한 과거형/완결 동사형 항목 skip
            if re.search(r'(?:었|였|겠)[습됩집합입]니다\.?\s*$', target):
                current_title = ""; details = []; return
        domain, _, signals = classify_unit(current_title, detail_str)
        sentence = format_final_sentence(target, _verb_key_to_final(ck))
        if sentence:
            units.append(_make_unit(len(units)+1, domain, target, ck, signals, sentence, clean_line(current_title), detail_str))
        current_title = ""
        details = []

    has_numbered = any(re.match(r"^\s*\d{1,2}[.)\s]", l) for l in section)
    for line in section:
        if _SKIP_HDR.match(line):
            continue
        if re.search(r"(Patch Note Details|Update Details|Known Issues|상세\s*내용)", line, re.I):
            break
        numbered = re.match(r"^\s*(\d{1,2})[.)]\s*(.+)$", line)
        if numbered:
            flush()
            current_title = clean_line(numbered.group(2))
            continue
        if re.match(r"^\s*\d{1,2}[.)]\s*$", line):
            flush(); continue
        if is_bullet_line(line):
            t = clean_line(line)
            if not t or len(t) < 4:
                continue
            if has_numbered and current_title:
                details.append(line)
            else:
                flush()
                current_title = t
                flush()
        elif current_title and not has_numbered:
            pass
        elif current_title and len(details) < 2 and not re.match(r"^[\[\]#<]", line):
            details.append(line)
        elif not current_title and not has_numbered and 4 <= len(clean_line(line)) <= 120:
            t = clean_line(line)
            if t and not re.match(r"^[\[\]#<※]", t):
                flush()
                current_title = t
    flush()
    return units[:14]


_EXCLUDE_B = re.compile(
    r"(바로가기|공지|https?://|자세한\s*내용"
    r"|참고해\s*주세요|클릭하여"
    r"|이용약관|공유하기|회사소개|^목록$"
    r"|이벤트\s*기간|시작\s*일시|종료\s*일시"
    r"|진행\s*기간|변경\s*(?:전|후)|확률|보상\s*정보"
    r"|구성품|구매\s*제한"
    r"|경험해\s*보세요|확인해\s*보세요|이용해\s*보세요"
    r"|참여해\s*보세요|즐겨\s*보세요"
    r"|신규\s*(?:추가|콘텐츠)?\s*및(?:\s*변경\s*사항?)?"
    r"|개선\s*및(?:\s*변경\s*사항?)?"
    r"|기타\s*(?:개선|변경)?\s*사항?"
    r"|변경\s*사항"
    r"|추가\s*및\s*변경"
    r"|및\s*변경\s*사항?$)",
    re.I,
)
_HDG_MARKERS = re.compile(
    r"(추가|변경|조정|개선|개편|시작|종료"
    r"|오픈|진행|밸런스|balance|class change|클래스\s*체인지"
    r"|시젠|기능|신규|새로운)",
    re.I,
)


def _b_priority(line):
    for score, pat in _B_PRIORITY:
        if pat.search(line):
            return score
    return 6 if _HDG_MARKERS.search(line) else 99


def _is_heading_b(line):
    t = clean_line(line)
    if not t or len(t) < 4 or len(t) > 80:
        return False
    if _EXCLUDE_B.search(t):
        return False
    if re.match(r"^\d{1,2}\s*[월.]\s*\d{1,2}|^\d{4}년", t):
        return False
    if re.search(r'(?:었|였|겠)?[습됩집합입]니다\.?\s*$', t):
        return False
    if re.search(r'(?:할\s*수\s*있|할\s*수\s*없|되어\s*있)\s*습니다', t):
        return False
    return _b_priority(t) < 99


def _next_bullet(lines, idx):
    for nxt in lines[idx+1: min(len(lines), idx+6)]:
        c = clean_line(nxt)
        if not c or _EXCLUDE_B.search(c):
            continue
        if is_bullet_line(nxt):
            return c
    return ""


def extract_section_b(game, lines):
    body_start = 0
    for i, line in enumerate(lines):
        if re.search(r"(자세한\s*사항|아래\s*내용|하단의\s*내용|업데이트\s*내용은\s*아래)", line):
            body_start = i + 1
            break
    candidates = []
    for i, line in enumerate(lines[body_start:], start=body_start):
        t = clean_line(line)
        if not t:
            continue
        if re.search(r"(즐겨찾기|공유하기|회사소개|이용약관|^목록$|^댓글$)", t):
            break
        if _is_heading_b(line):
            candidates.append((_b_priority(t), i, t, _next_bullet(lines, i)))
    candidates.sort(key=lambda x: (x[0], x[1]))
    seen = set()
    units = []
    for pri, _, title, detail in candidates:
        if len(units) >= 16:
            break
        domain, ck, signals = classify_unit(title, detail)
        parsed = _parse_a_line(title)
        if parsed:
            target, ck2 = parsed
            sentence = format_final_sentence(target, _verb_key_to_final(ck2))
        elif re.search(r'(?:었|였|겠)?[습됩집합입]니다\.?\s*$', title):
            sentence = title.rstrip('.').strip() + '.'
        else:
            target = _extract_target_b(title)
            ck2 = ck
            sentence = format_final_sentence(target, _verb_key_to_final(ck2))
        if not sentence:
            continue
        key = norm_key(sentence)
        if key in seen:
            continue
        seen.add(key)
        units.append(_make_unit(len(units)+1, domain, target, ck2, signals, sentence, title, detail))
    return units


def _extract_target_b(title):
    t = clean_line(title)
    t = re.sub(r'\s+(?:안내|예정|사항)\s*$', '', t).strip()
    for kp, _ in _KO_NOUN_VERB:
        t2 = re.sub(r"\s+" + re.escape(kp) + r"\s*$", "", t).strip()
        if t2 and t2 != t:
            return t2
    t2 = re.sub(r"\s+(?:will\s+(?:be\s+)?)?(?:added|adjusted|improved|changed|commenced|started|ended|opened|introduced)\.?\s*$", "", t, flags=re.I).strip()
    return t2 if t2 and t2 != t else t


def _make_unit(order, domain, target, change_key, signals, sentence, source_heading, source_context):
    return {
        "order": order,
        "domain": domain,
        "target": target,
        "change_type": change_key,
        "signals": signals,
        "normalization_flags": [],
        "quality_flags": [],
        "source_heading": source_heading,
        "source_context_excerpt": source_context,
        "summary_sentence": sentence,
        "confidence": 0.9,
        "profile_rule": "source_section_extractor_v2",
    }


def _dedupe(units):
    out = []
    seen = set()
    for unit in units:
        key = norm_key(unit.get("summary_sentence", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        u = dict(unit)
        u["order"] = len(out) + 1
        out.append(u)
    return out[:16]


def _quality_check(unit):
    flags = []
    tgt = unit.get("target", "")
    if not tgt:
        flags.append("EMPTY_TARGET")
    if norm_key(tgt) in _LOW_VALUE:
        flags.append("GENERIC_TARGET")
    if len(tgt) > 120:
        flags.append("OVERLONG_TARGET")
    return flags


SUPPORTED_GAMES = {"MIR4_KR", "MIR4_Global", "NightCrows_Global", "NightCrows_KR", "Odin_KR"}


def extract_units(game, text):
    if game not in SUPPORTED_GAMES:
        return [], ["UNSUPPORTED_GAME"], "none"
    lines = split_lines(text)
    section = find_section(lines, SECTION_START_PATTERNS, SECTION_END_PATTERNS)
    if section:
        units = extract_section_a(game, section)
        route = "4-A"
    else:
        units = extract_section_b(game, lines)
        route = "4-B"
    for unit in units:
        unit["quality_flags"] = _quality_check(unit)
    units = _dedupe(units)
    good = [u for u in units if not u.get("quality_flags")]
    dropped = []
    for u in units:
        for f in u.get("quality_flags", []):
            if f not in dropped:
                dropped.append(f)
    flags = []
    if not good and units:
        flags.extend(f for f in dropped if f not in flags)
        good = units
    if not good:
        flags.append("SUMMARY_SECTION_NOT_FOUND_OR_EMPTY")
    return good, flags, route


def section_summary_preview(game, text):
    units, flags, route = extract_units(game, text)
    body = [str(u.get("summary_sentence", "")) for u in units if u.get("summary_sentence")]
    tags = []
    signals = []
    for unit in units:
        domain = str(unit.get("domain", ""))
        if domain and domain not in tags:
            tags.append(domain)
        for sig in unit.get("signals", []) or []:
            if sig not in signals:
                signals.append(sig)
    return {
        "body_summary": body,
        "domain_tags": tags,
        "card_summary": " / ".join(tags[:4]),
        "units": units,
        "signals": signals,
        "quality_status": "PASS" if body and not flags else "REVIEW",
        "flags": flags,
        "quality_warnings": [],
        "route": route,
    }


def extract_source_section_units(game, text):
    units, flags, _ = extract_units(game, text)
    return units, flags


def major_from_signals(signals):
    MAJOR = {"new_class", "new_system", "new_region", "new_pve_content", "new_pvp_war", "new_world_content", "server_merge", "server_transfer", "major_rework"}
    return any(s in MAJOR for s in signals or [])
