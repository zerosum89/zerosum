# v079 Package Release Gate

## 목적

v079는 이후 생성되는 로컬 실행 패키지가 사용자 환경에서 반복적으로 실패하지 않도록, 패키지 릴리즈 전 최소 검증 항목을 코드로 강제한다.

## 단일 책임

이 gate는 패치노트 수집, Notion write, Git push, HTML 렌더링을 수행하지 않는다.
오직 **패키지 자체가 실행 가능한 형태인지**만 검증한다.

## 강제 검증 항목

| 항목 | 기준 |
|---|---|
| ZIP 구조 | ZIP 내부 루트 폴더명이 ZIP 파일명과 동일 |
| 실행 파일 | `01_RUN.cmd`, `01_RUN.sh` 존재 |
| 기본 폴더 | `scripts/`, `inputs/`, `outputs/deliverables/` 존재 |
| 폴더 자동 열기 | Windows는 `explorer outputs\deliverables` 포함 |
| Python 문법 | `compile()` 기반, `.pyc` 생성 없음 |
| delivery ZIP | entry count와 size 기록, 빈 ZIP 차단 |
| 위험 동작 | `git push`, Notion write는 명시 허용 없으면 차단/경고 |
| 금지 산출물 | `__pycache__`, `.pyc`, `.DS_Store` 포함 금지 |

## 패키지 완료 정의

패키지는 아래 모두 통과해야 사용자에게 전달 가능하다.

```text
function_gate = pass
package_gate = pass
delivery_zip_entry_count > 0
outputs/deliverables auto-open configured
notion_write / git_push scope explicitly declared
```

## 사용 위치

향후 패키지 생성 시에는 내부 생성 직후 아래 순서로 실행한다.

```text
1. package_release_gate_v079.py --package-root <package>
2. ZIP 생성
3. package_release_gate_v079.py --package-root <package> --package-zip <zip>
4. 내부 mock 실행
5. delivery ZIP entry count 확인
6. 사용자 전달
```
