# Odin_KR detail cleanup v022

## 목적

Daum Cafe 상세 페이지에서 HTML 태그, 카페 내비게이션, 댓글 영역이 update-unit 후보로 섞이는 문제를 차단한다.

## 변경 사항

- `m.cafe.daum.net/odin/DEH7/{id}` 모바일 텍스트 variant를 우선한다.
- `_c21_/bbs_read` variant는 HTML을 visible text로 변환한 뒤에만 평가한다.
- `업데이트에 대한 자세한 내용` 또는 `업데이트 상세 내역 안내`부터 `감사합니다.`까지를 본문 구간으로 사용한다.
- `이전글`, `목록`, `댓글`, `저작자 표시`, 사용자 댓글 문구를 제거한다.
- Odin_KR 이벤트/상품형 업데이트는 보수적으로 `PvP/전쟁`, `이벤트/보상`, `상점/BM`, `경제/보상` 단위로 요약 후보를 만든다.

## write 기준

본문 정제 후에도 update-unit 후보가 부족하거나 오염 문장이 남으면 `write_ready=false`로 유지한다.
