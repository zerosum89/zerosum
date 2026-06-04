# GitHub Actions setup

## Required repository secrets

Repository Settings → Secrets and variables → Actions → New repository secret.

Required:

```text
NOTION_TOKEN
NOTION_DATABASE_ID
```

Optional, later summary/write stage only:

```text
OPENAI_API_KEY
```

## First run

1. Actions tab
2. Patchnote Update Workflow
3. Run workflow
4. `dry_run=true`
5. `run_git_push=false`
6. Download `patch-update-artifacts`

## Manual JSON export push

Only after preview is checked:

```text
dry_run=false
run_git_push=true
run_notion_write=false
```

v009 never performs Notion write.


## v009 실행 식별자 / URL 후보 검증

- artifact에 `execution_identity.json`을 생성합니다.
- `workflow_version`, `GITHUB_SHA`, `GITHUB_REF`, `GITHUB_RUN_ID`, `script_sha256`를 기록합니다.
- `detail_url_guard.json`과 `invalid_url_candidates.csv`로 board/list URL 후보 잔존 여부를 검증합니다.
- `STRICT_DETAIL_URL_GUARD=true`이면 board/list URL이 신규 후보에 남는 즉시 workflow를 실패 처리합니다.


## v009 addition

New URL candidates can be followed to detail pages in preview mode. The workflow stores raw HTML/TXT artifacts and creates conservative rule-based summary candidates. These candidates are not write-ready; Notion write remains disabled.


## v016 MIR4_KR summary repair

- MIR4_KR 신규 패치 요약 후보에서 `현신도`는 성장/장비로 분류합니다.
- `변경 사항이 반영됩니다` filler 문구가 남으면 품질 플래그를 부여합니다.
- MIR4_KR 신규 write는 summary preview 확인 후 진행합니다.

## v024 schedule 운영 설정

정기 실행은 매일 06:00 KST 전후에 실행된다. 기본값은 preview-only이다.

자동 write/deploy까지 켜려면 repository variable을 추가한다.

```text
Settings → Secrets and variables → Actions → Variables → New repository variable
Name: PATCH_UPDATE_SCHEDULE_MODE
Value: write_deploy
```

초기 안정화 기간에는 이 variable을 만들지 않거나 `preview`로 둔다.
