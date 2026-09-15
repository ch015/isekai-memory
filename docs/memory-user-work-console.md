# M9 사용자 작업 TUI와 독립 lease 제어

2026-09-14 로컬 구현·합성 DB/HTTP 검증. 실제 구독 CLI 실행, 운영 활성화·배포·커밋·푸시는 하지 않았다.
M9-5 사용자 작업 연결 계약이다. [M9 완료 검증표](memory-m9-acceptance.md)와
[변경 feed/catch-up 계약](memory-collaboration-events.md)을 함께 따른다.

## 사용

```sh
# 기본 관찰: local State/claim/worker 변경 없음
isekai --project /path/to/project watch

# 기존 프로젝트의 continuity opt-in이 켜져 있어야 함. 매번 새 작업 세션.
isekai --project /path/to/project watch --work

# 명시적으로 같은 세션 재접속 (콘솔 상단/종료 메시지의 UUID)
isekai --project /path/to/project watch --work --work-session-id <UUID>

# 같은 바이너리에서 관리 기능도 열기. 서버 권한을 추가하지는 않음.
isekai --project /path/to/project watch --work --manage
```

`--work`는 원격 전용 `--profile` 또는 `--once`와 함께 쓸 수 없다. 새 로그인은 추가하지 않았다.
사용자는 Git author가 아니라 Memory가 검증한 기존 토큰의 actor다. 같은 actor의 두 세션도 claim capability 파일을 공유하지 않는다.
세션 ID 자체는 인증 수단이 아니며 동일 OS 계정의 파일 접근은 별도 보안 경계가 아니다.

## 작업 흐름

```text
내 인수함/작업에서 행 선택 → w → 전달/담당 작업 확인
  → 검증 조회 → 인수 확인(다른 인수자의 확인 상태는 그대로)
  → 작업 선택·소유권 취득 → 필요하면 독립 갱신 시작
  → 격리 준비 → 기존 Core 경로에서 파일 검사·실행 승인·작업
  → 완료 또는 반납

g → 기존 로컬 unit ID 입력 → 저장본 업로드 미리보기·확인
내 저장본 행 선택 → w → 정책의 인수자별 독립 작업(1:N) 확인 → 인계

y → 이 세션의 미확정 요청 확인 → 같은 요청 재확인 또는 로컬 요청 폐기
```

모든 변경은 전체 요청 페이지와 확인란을 거친다. 준비는 원본 작업 디렉터리를 덮어쓰지 않는다.
완료는 사용자 보고이며 검사/실행 성공을 서버가 검증했다는 뜻이 아니다.
사용자 모드의 인계는 본인 저장본으로 한정한다. 관리자도 다른 사람의 복구 발행은 별도 관리자 메뉴를 사용한다.
인수자는 관리자 정책의 기본/인계자별 규칙에서 가져오며, 예비 인수자를 임의로 승격하지 않는다.

## 경계와 재시도

- 관찰/작업 모드 생성·미리보기는 Kernel/SQLite를 열지 않는다. 확인된 capture/inspect/prepare만
  작업 스레드 안에서 기존 Core runtime을 열고 닫는다. MCP의 activation/caller 검증은 유지된다.
- project/actor/endpoint/credential reference/작업 세션/로컬 config digest/active Lock을 고정하고 재확인한다.
  사용자·설정·Lock 변경 시 자동으로 다른 연결에서 재실행하지 않는다.
- claim은 선택 시 본 routing version과 generation을 서버 트랜잭션에서 확인한다.
  응답 유실 시 원래 capability로 동일 세대만 재확인한다. 다른 세션은 그 capability를 자동 채택하지 않는다.
- owner-only 단일 미확정 요청(최대 40 KiB, 7일 재시도 한도), 비차단 프로세스 간 잠금.
  성공 또는 명시적 폐기 시 요청 파일 삭제. 폐기는 서버 변경 취소가 아니다.
  원격 본문/스냅샷/bearer/claim token은 이 요청 기록에 넣지 않는다.
- capture/prepare는 고정 request UUID를 지원한다. 동일 요청의 저장본/격리 폴더를 재사용하되
  불완전한 복원 디렉터리는 자동 덮어쓰기·실행하지 않고 명시적 로컬 확인을 요구한다.
  자동 checkpoint capture는 기존 주기별 새 버전 동작을 유지한다.
- 실제 claim capability와 복원 파일은 기존 Core owner-only 저장 경로의 책임이다.
  확인 전후 객체가 바뀔 수 있으므로 최종 서버·Core 검증 실패 시 중단한다.

## 독립 갱신기

```sh
isekai --project /path/to/project memory lease-keepalive \
  --work-session-id <UUID> --unit-id <UUID> --claim-generation 1 \
  --actor-id <Memory-user> --duration-seconds 3600

# 현재 세션/작업/세대의 갱신기에 중지 요청만 전달
isekai --project /path/to/project memory lease-keepalive \
  --work-session-id <UUID> --unit-id <UUID> --claim-generation 1 --stop
```

TUI 시작 버튼은 위 전용 Core 프로세스를 shell 없이 분리 실행한다. 기본 1시간, 최대 24시간이며
기존 소유권만 갱신한다. 새 claim, worker 시작/중지, 승인, presence heartbeat는 수행하지 않는다.
TUI 종료가 갱신기 종료나 반납을 의미하지 않는다. 중지는 다음 주기(최대 60초)에 반영된다.
갱신이 멈춰도 마지막으로 확인한 lease 만료 시각까지 소유권이 남을 수 있다.

서버 시간 기준 절대 만료 시각으로 갱신하고 응답 유실 시 같은 시각을 재시도한다.
권한/사용자/정책/설정/소유 세대 오류는 자동 재획득 없이 중단한다. 확인한 시작 요청 ID를 재전송해도
이미 종료한 갱신기를 되살리지 않는다. 명시적 시작 이력은 세션당 256개 한도이며 한도 도달 시
확인되지 않은 기록을 자동 삭제하지 않고 운영자 확인을 요구한다.
콘솔의 시작 결과는 `launch_requested`이지 갱신/실행 성공 확인이 아니다.

## 검증

- Core 사용자 작업/TUI/기존 continuity/lease/세션 테스트: **75 passed**.
- Workbench + enforced/package 경계 검사: **37 passed** (위 작업 테스트 일부 포함; 합산 수치 아님).
- 전체 HTTP/stdio 하네스: 기존 M0–M9 및 새 `core_work_e2e_smoke.py` 통과.
  서로 다른 두 인수자의 Textual 확인 → HTTP ack 독립성 → claim 응답 유실 → 같은 세대 재확인 →
  독립 keeper 갱신/중지 → 격리 준비 동일 요청 재사용 → 완료 검증.
- 80×24/120×36 합성 터미널. 실제 Codex/Claude/Kiro 구독 계정 실행 검증은 아니다.
