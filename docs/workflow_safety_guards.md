# Workflow safety guards

| Guard | Rule |
|---|---|
| HTML guard | workflow must not change index.html |
| Data-only guard | commit step allows patch_view_model.json only |
| Anchor missing | write disabled, preview REVIEW only |
| Schedule run | preview-only by default |
| Notion write | disabled in v004 |
| No noisy commits | if exported items equal current JSON items, existing file is preserved |


## v004 URL candidate guard

- Board/list URLs are excluded from `new_url_candidates`.
- Game profiles must define `detail_url_include_patterns` for detail pages.
- MIR4 KR anchor matching applies the configured host alias before comparison.
