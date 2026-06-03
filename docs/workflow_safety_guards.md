# Workflow safety guards

| Guard | Rule |
|---|---|
| HTML guard | workflow must not change index.html |
| Data-only guard | commit step allows patch_view_model.json only |
| Anchor missing | write disabled, preview REVIEW only |
| Schedule run | preview-only by default |
| Notion write | disabled in v003 |
| No noisy commits | if exported items equal current JSON items, existing file is preserved |
