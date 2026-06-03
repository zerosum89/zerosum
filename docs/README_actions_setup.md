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

v004 never performs Notion write.
