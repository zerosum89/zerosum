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

v006 never performs Notion write.


## v006 실행 식별자 / URL 후보 검증

- artifact에 `execution_identity.json`을 생성합니다.
- `workflow_version`, `GITHUB_SHA`, `GITHUB_REF`, `GITHUB_RUN_ID`, `script_sha256`를 기록합니다.
- `detail_url_guard.json`과 `invalid_url_candidates.csv`로 board/list URL 후보 잔존 여부를 검증합니다.
- `STRICT_DETAIL_URL_GUARD=true`이면 board/list URL이 신규 후보에 남는 즉시 workflow를 실패 처리합니다.
