# Patch Summary Quality Contract

## Purpose

`body_summary` is a compressed card summary, not a source-section dump.

The summary must help a reader understand the patch at a glance in the HTML card.
It must not list every event, package, shop item, or bug fix.

No Notion write, export, commit, or push may proceed unless this contract passes.

## Field Responsibilities

### body_summary

Compressed summary of the patch.

Rules:
- Keep 5 to 8 lines by default.
- Allow up to 10 lines only when there are multiple structural updates.
- Fail above 10 lines.
- Prioritize structural changes first:
  - new class or job
  - new region, chapter, dungeon, raid, boss, war, battleground
  - new growth system, equipment axis, stat axis, artifact, collection system
  - server/world structure changes
  - economy, crafting, trade, or major rule rework
- Put operational changes after structural changes:
  - balance, UI, convenience, bug fixes
  - events
  - shop/package/product changes
- Do not preserve source order if it harms summary quality.
- Do not copy every source heading.
- Do not use title fragments or noun-only lines.

### main_updates

Top summary lines selected by importance, not `body_summary[:3]`.

Rules:
- 2 to 3 lines.
- Must prefer structural changes from `body_summary`.
- Must not start with event, package, shop, sale, or bug-fix lines when structural lines exist.
- If no structural change exists, use the most concrete gameplay/system lines.

### primary_category

Representative patch category.

Rules:
- 1 to 3 categories.
- Must represent the highest-impact summary lines.
- Must not contain every detected category.
- Event/shop categories must not dominate when structural categories exist.

### domain_tags

Full detected related domains.

Rules:
- May contain broader detected domains.
- Must not be used directly as `primary_category`.
- Empty `domain_tags` is allowed only if `primary_category` is present.

### importance_decision

Major/normal display decision.

Rules:
- Derived from structural `body_summary` lines.
- `importance` and `importance_decision` must not conflict in exported public JSON.
- `major` requires at least one highlight candidate.
- Event/shop/bug-fix-only patches must not become `major`.

## Compression Rules

### Events

Events are supporting information.

Rules:
- Maximum 2 event lines.
- If more than 2 source events exist, compress:
  - `2주년 기념 출석·핫타임·미션 이벤트가 진행됩니다.`
  - `커뮤니티 이벤트와 보상 이벤트가 함께 진행됩니다.`
- Do not list all event names.
- Remove generic event lines if concrete compressed event lines exist.
- Fail if `이벤트가 진행됩니다.` appears 3 or more times in one `body_summary`.

### Shop and Packages

Shop/package updates are supporting information.

Rules:
- Maximum 1 shop/package line.
- Do not list package names unless the patch is primarily a shop-only update.
- Compress:
  - `신규 패키지와 일부 상품 판매 종료가 반영됩니다.`
  - `캐시샵 상품 구성과 판매 일정이 변경됩니다.`
- Fail if package/shop/product lines exceed 1.

### Bug Fixes

Bug fixes are supporting information.

Rules:
- Maximum 1 bug-fix line.
- Compress:
  - `전투, UI, 퀘스트 관련 오류가 수정됩니다.`
  - `플레이/UI 관련 오류가 수정됩니다.`
- Do not list individual bug fixes unless the patch is bug-fix-only and there is a major service-impacting fix.

### Long Lines

Rules:
- Fail if a line exceeds 120 characters.
- Split or compress long lines.
- Do not split into fragments that lose sentence meaning.

### Generic Lines

Generic lines are allowed only as compressed support lines.

Examples:
- Allowed once: `플레이/UI 관련 오류가 수정됩니다.`
- Allowed once: `신규 패키지와 판매 종료 상품이 반영됩니다.`
- Not allowed repeatedly: `신규 이벤트가 진행됩니다.`
- Not allowed with concrete event lines: `신규 인게임 이벤트가 진행됩니다.`

## Harness Requirements

The harness must run before every Notion write and before every git commit/push.

It must fail on:
- `body_summary` line count greater than 10.
- event lines greater than 2.
- shop/package/product lines greater than 1.
- bug-fix lines greater than 1.
- line length greater than 120 characters.
- title-like or noun-only lines.
- broken quotes or brackets.
- particle errors.
- duplicate generic and concrete event/shop lines together.
- `main_updates` equals the first 3 body lines without ranking when structural lines exist later.
- `main_updates` starts with event/shop/bug-fix while structural lines exist.
- `primary_category` has more than 3 categories.
- `primary_category` contains only event/shop while structural lines exist.
- `importance` and `importance_decision` conflict in public JSON.
- `major` without highlight candidates.
- event/shop/bug-fix-only patch marked `major`.

The harness report must include:
- total item count
- failed item count
- failure type counts
- game counts
- changed candidate count
- before/after examples
- top 30 failed items
- CSV and JSON artifacts

## Required Workflow

No shortcut is allowed.

1. Generate candidate file only.
2. Run full summary-quality harness.
3. Show report to user.
4. Wait for user approval.
5. Run dry-run against Notion.
6. Show dry-run result.
7. Wait for user approval.
8. Apply to Notion.
9. Re-run dry-run and confirm zero remaining changes.
10. Export `patch_view_model.json`.
11. Run full summary-quality harness on exported JSON.
12. Run policy gate.
13. Show final report.
14. Wait for user approval before commit.
15. Commit.
16. Wait for user approval before push.
17. Push.

If any step fails, stop. Do not continue with a partial workaround.

## Non-Goals

- Do not maximize detail.
- Do not list all events.
- Do not list all packages.
- Do not convert source headings directly into summary lines.
- Do not treat BeautifulSoup extraction as a summary by itself.
- Do not use `body_summary[:3]` as `main_updates`.

## Example

Bad:

```text
- 신규 전직 클래스 '바드'가 추가됩니다.
- 신규 정예 던전 '무한의 탑'이 추가됩니다.
- 2주년 기념! 21일 출석 이벤트가 진행됩니다.
- 2주년 기념! 특별 핫타임 이벤트가 진행됩니다.
- 2주년 기념! 가위바위보 하나빼기 이벤트가 진행됩니다.
- 신규 패키지가 추가됩니다.
- 월간/주간 특별 패키지가 추가됩니다.
- 한정 팝업이 추가됩니다.
```

Good:

```text
- 신규 전직 클래스 '바드'가 추가됩니다.
- 신규 정예 던전 '무한의 탑'이 추가됩니다.
- 신규 무기 형상과 스킬 기술서 제작식이 추가됩니다.
- 2주년 기념 콘텐츠와 이벤트가 진행됩니다.
- 치명타 공식과 UI/표기 관련 개선이 반영됩니다.
- 캐시샵 상품 판매 종료 및 신규 패키지가 반영됩니다.
```
