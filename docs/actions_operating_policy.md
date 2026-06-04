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

## v024 정기 운영 안정화 기준

### 기본 원칙

- scheduled run은 기본값으로 preview-only로 실행한다.
- 자동 write/deploy는 repo variable `PATCH_UPDATE_SCHEDULE_MODE=write_deploy`를 명시적으로 설정한 경우에만 활성화한다.
- 수동 `workflow_dispatch` 실행은 기존 입력값을 그대로 우선한다.
- data-only deploy guard는 계속 유지한다. `patch_view_model.json` 외 변경이 감지되면 실패한다.

### Repository variables

선택적으로 아래 변수를 사용할 수 있다. 설정하지 않으면 preview 안전값을 사용한다.

| Variable | 기본값 | 설명 |
|---|---|---|
| `PATCH_UPDATE_SCHEDULE_MODE` | `preview` | `preview` 또는 `write_deploy` |
| `PATCH_UPDATE_TARGET_GAMES` | `ALL` | schedule 대상 게임 |
| `PATCH_UPDATE_MAX_NEW_URLS_PER_GAME` | `20` | 게임별 신규 URL 상한 |
| `PATCH_UPDATE_STRICT_DETAIL_URL_GUARD` | `true` | 목록/board URL 후보 차단 |
| `PATCH_UPDATE_FETCH_DETAIL_PAGES` | `true` | 상세 원문 수집 여부 |
| `PATCH_UPDATE_MAX_DETAIL_FETCHES` | `20` | 실행당 상세 fetch 상한 |
| `PATCH_UPDATE_RUN_TITLE_REPAIR` | `false` | schedule에서 title repair 수행 여부 |
| `PATCH_UPDATE_TITLE_REPAIR_WINDOW_DAYS` | `14` | title repair 대상 기간 |

### 운영 전환 순서

1. 3~7일간 `PATCH_UPDATE_SCHEDULE_MODE` 미설정 상태로 scheduled preview를 관찰한다.
2. artifact의 `operation_mode_guard.json`, `workflow_report.md`, `detail_url_guard.json`을 확인한다.
3. 신규 후보 품질이 안정적이면 `PATCH_UPDATE_SCHEDULE_MODE=write_deploy`를 설정한다.
4. 자동 write/deploy 전환 후에도 실패 시 artifact를 기준으로 원인을 확인한다.
