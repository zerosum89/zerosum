# Actions operating policy

## Standard flow

```text
GitHub Actions
→ Notion DB export
→ patch_view_model.json generation
→ game anchor detection
→ official list fetch
→ newer-than-anchor URL detection
→ payload preview artifact
→ optional patch_view_model.json data-only commit
```

## New URL rule

```text
anchor = last loaded patchnote per game
new_url_candidates = all official URLs newer than anchor
processing_order = oldest-first
```

## v009 scope

- Notion write: disabled
- HTML change: forbidden
- data.json: not used
- commit target: patch_view_model.json only


## v009 실행 식별자 / URL 후보 검증

- artifact에 `execution_identity.json`을 생성합니다.
- `workflow_version`, `GITHUB_SHA`, `GITHUB_REF`, `GITHUB_RUN_ID`, `script_sha256`를 기록합니다.
- `detail_url_guard.json`과 `invalid_url_candidates.csv`로 board/list URL 후보 잔존 여부를 검증합니다.
- `STRICT_DETAIL_URL_GUARD=true`이면 board/list URL이 신규 후보에 남는 즉시 workflow를 실패 처리합니다.


## v009 addition

New URL candidates can be followed to detail pages in preview mode. The workflow stores raw HTML/TXT artifacts and creates conservative rule-based summary candidates. These candidates are not write-ready; Notion write remains disabled.


## v015 title rule

신규 Patch View Model page의 Notion title property(`항목명`)는 원문 제목이 아니라 `actual_date` 기반 `YY.MM.DD | 패치노트`로 생성합니다. 원문 제목은 `source_page_title`로 보존합니다.


## v016 MIR4_KR summary repair

- MIR4_KR 신규 패치 요약 후보에서 `현신도`는 성장/장비로 분류합니다.
- `변경 사항이 반영됩니다` filler 문구가 남으면 품질 플래그를 부여합니다.
- MIR4_KR 신규 write는 summary preview 확인 후 진행합니다.
