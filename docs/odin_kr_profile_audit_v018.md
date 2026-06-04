# Odin_KR profile audit v020

## Purpose

Fix Odin_KR official-list detection in GitHub Actions.

## Confirmed source shape

- Official landing page: `https://odin.game.daum.net/odin/`
- The page exposes a `새소식` block.
- Recent update entries link out to Daum Cafe, for example `https://cafe.daum.net/odin/DEH7/258`.
- Update titles follow the shape `[업데이트] 6/3(수) 업데이트 상세 내역 안내`.

## Detection rule

```text
anchor = latest Odin_KR source_url in Patch View Model
list = official homepage recent news links
candidate = detail URL under cafe.daum.net/odin/DEH7/{id}
newer-than-anchor = actual_date > anchor.actual_date
```

The homepage exposes a short recent-news window, so the stored anchor may not appear in the visible list. v020 allows profile-specific date fallback:

```json
"anchor_missing_date_fallback_as_pass": true
```

This applies only when a candidate has an actual_date newer than the anchor.

## Guard

List/board URLs remain excluded. Only detail-like Daum Cafe URLs are accepted.

## Write policy

Odin_KR should be verified with dry-run first. If detail fetch fails due to Daum Cafe access restrictions, write remains skipped by payload quality guard.
