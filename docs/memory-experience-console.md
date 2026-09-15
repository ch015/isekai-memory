# M9 경험 검색·제안 검토 TUI

상태: 구현 및 단위/실제 localhost HTTP 합성 검증, 2026-09-14.
관리자 핵심 협업 폼에 남았던 경험 검토를 연결한다. M9 전체 완료는 아니며
사용자 로컬 작업/lease 제어기와 durable event 복구가 남아 있다.

## 사용 흐름

`isekai watch`의 기억 탭에서 k: 승인된 프로젝트 기억 검색,
`isekai watch --manage`에서 v: 관리자 경험 제안 검토.
기억 탭 진입과 주기적 poll은 본문/검색/검토 API를 호출하지 않는다.

검색어 입력 → 명시적 검색 → 제한된 결과 목록 → 선택 상세 → 출처 결박 검증 후 전체 내용.
검색은 승인·유효기간·분류가 적용된 기존 memory_search/read를 사용한다.
검색 결과는 reference_only이며 실행 명령·정책·권한이 아니다.
20개/16,000자 결과 한도와 잘림 표시가 있으며 좁은 검색으로 다시 조회한다.

관리자 제안 목록 → 선택 상세 → 출처·버전·전체 내용 페이지 확인 →
승인/거절 미리보기 → 명시적 최종 확인 → 서버 receipt → 목록 재조회.
원본 handoff ID/Lock·payload digest와 제안의 출처 결박을 검증한다.
원본 작업 receipt가 곧 제안 내용의 참이라는 뜻은 아니며 자동 승인하지 않는다.
archive/forget/수정 제안·suppression 관리는 기존 API에 남는다; 이 화면은 pending 승인/거절이다.

## 계약과 경계

- 기존 memory_experience_list에 metadata_only, max_classification, memory_id를 추가했다.
  기존 호출 기본은 본문 포함/분류 restricted로 유지한다. TUI는 internal 기본,
  metadata_only=true의 명시적 페이지 조회다. 본문·source·tags는 목록 SQL에서 제외한다.
- 상세는 동일 도구의 정확한 memory_id와 metadata_only=false로 한 건 조회한다.
  분류·프로젝트·pending 조건을 LIMIT 전에 적용한다. 읽기 전용 snapshot/유한 시간 예산을 쓴다.
- queue-v2 cursor는 actor/project/status/분류/metadata 모드/정확한 ID에 결박된다.
  이전 queue cursor는 새 페이지에서 재시작해야 한다. 전체 감사/알림 feed가 아니다.
- 응답의 actor/project/분류·페이지 정합성을 검증한다. 검색 excerpt/binding/content
  digest와 상세 content digest를 검증하고, 출처 불일치·본문 위조는 차단한다.
- 신원 조회와 API 호출은 같은 credential snapshot이다. 일반 사용자는 pending
  목록/승인에 접근할 수 없다. 새 actor/인증 철회는 과거 성공값으로 대체하지 않는다.
- 검토의 멱등 키는 기존 서버 계약인 프로젝트·인증 actor·memory ID·예상 버전·동작이다.
  별도 가짜 idempotency_key를 서버에 보내지 않는다. 응답 유실 시 동일 요청만 재전송한다.
- 공통 owner-only 미확정 관리 기록에 ID/동작/버전만 저장한다. 본문·원문 출처·토큰은
  저장하지 않으며 확인/폐기 후 요청도 지운다. 기존 7일/단일 요청/교차 프로세스 잠금을 재사용한다.
- 모든 상세 내용 페이지를 확인해야 미리보기로 진행할 수 있다. 2048자를 넘는
  본문도 조용히 잘리지 않는다. ANSI/OSC/Rich 문자열은 명령이 아니라 정제된 텍스트다.
- 관찰 시작은 Kernel/SQLite를 열지 않으며 검색/검토도 로컬 작업 실행과 무관하다.

## 검증

Memory 경험/권한/metadata queue 관련 81개, Core 신규 계약·TUI 18개,
기존 TUI 회귀 92개 통과. 80x24·120x36, 전체 본문 끝부분 표시,
일반 사용자 검색, 관리자 승인, 응답 유실 후 정확한 동일 버전 재시도를 검증했다.
실제 localhost HTTP에서도 관리자 TUI 승인 → 다른 사용자 TUI 검색/상세 조회와
중복 승인 방지·본문 없는 pending 기록을 확인했다. 전체 Memory 회귀 636개 통과.
실제 구독 CLI 계정·운영 프로젝트는 사용하지 않았다.
