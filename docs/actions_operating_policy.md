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

## v003 scope

- Notion write: disabled
- HTML change: forbidden
- data.json: not used
- commit target: patch_view_model.json only
