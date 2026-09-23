# M9 협업 TUI 구현 준비서

현재 배포는 Memory schema **020**을 사용한다. [운영 갱신](multiuser-operation.md)과
[자료·이력 공유](project-sharing.md)가 현재 기준이다. 아래 M9 설계·검증 수·schema 번호는
2026-09-14/15 당시의 기록이며 최신 서버 또는 ADE 화면의 인수를 뜻하지 않는다.

후속 [전체 프로젝트 연결 목록·전환](memory-multi-project-console.md) 적용 후에는
기본 watch가 전역 목록이며, 기존 단일 프로젝트 진입은 --project를 명시한다.

상태: **M9 로컬 구현·합성 검증 완료**. 완료 기록: 2026-09-15.
[완료 검증표](memory-m9-acceptance.md), [사용자 작업](memory-user-work-console.md),
[변경 알림](memory-collaboration-events.md), [컨트롤러 관측](memory-controller-runtime.md),
[경험 검색·검토](memory-experience-console.md), [토큰 관측](memory-usage-runtime.md)을 따른다.
M9 검증 당시 Memory schema 013 / 82 tools. 기존 M8 계약·미커밋 변경을 보존한다.
실제 구독 계정 실행, 운영 활성화·배포·커밋·푸시는 검증 범위 밖이다.
사용자의 최종 범위 확인에 따라 토큰 사용량과 미수집 여부 표시가 핵심이며,
비용 계산·예산·결제 개발은 범위 밖이다. 이미 구현된 선택 알림은 기본 꺼짐이다.

## 1. 결정과 범위

- 사용자와 관리자 모두 **하나의 TUI**를 사용한다. 관리자 웹 화면은
  필수 구성이나 다음 단계의 전제조건이 아니다.
- 새 로그인·Nunchi 인증 연동은 후속으로 보류한다. 이번 TUI는 기존 Memory
  사용자별 프로젝트 토큰과 credential_ref를 사용하며 인증을 생략하지 않는다.
- 사용자별 idle과 모델 토큰 사용량을 함께 보여준다. 사용량은 보고치/추정치/
  미수집을 구분하며 컨텍스트 점유율·실제 요금·구독 잔여 한도와 혼동하지 않는다.
- 터미널 분할 패널에서 상시 조회하고, 관리자도 같은 화면의 폼으로
  1:N 인수자 지정, 정책 편집, 복구 발행, 재배정, 감사 조회를 수행한다.
- 기본 모드는 관찰 전용. 관리 모드를 열어도 권한은 늘어나지 않는다.
  서버가 확인한 프로젝트별 권한에 해당하는 동작만 제공한다.
- Memory는 인증·저장·배정의 기준, Core는 실제 작업과 로컬 승인·복원의
  기준이다. TUI는 두 경계를 연결하는 표시/입력 계층이지 새 실행 엔진이 아니다.
- CLI 화면 스크래핑, 전체 대화/프롬프트 업로드, 전역 관리자 토큰 공유,
  자동 인수·자동 재배정·자동 실행을 도입하지 않는다.
- M9-1부터 M9-6까지 조회, worker/controller 관측, 토큰 관측, 사용자·관리자 TUI,
  기존 Core 작업 연결, 독립 lease 갱신기와 내구성 있는 변경 조회를 구현했다.
  실제 프로젝트 활성화, 배포, 커밋·푸시는 별도 요청 없이 수행하지 않는다.

## 2. 사용자 경험

현재 진입점(관찰 기본값; 관리 변경은 별도 확인):

```text
isekai watch           -> 관찰 모드: 내 작업 / 인수함 / 인계함 / 현황
isekai watch --work    -> 로컬 사용자 작업: 확인/claim/격리 준비/저장/인계/반납; 명시적 확인 필요
isekai watch --manage  -> 정책·복구 발행·재배정·삭제·감사; 서버 관리자 권한과 명시적 확인 필요
```

프로젝트의 Memory 설정을 읽거나 등록된 로컬 연결 프로필을 선택한다.
관리자는 소스 저장소/활성 Lock 없이도 자신의 프로젝트 관리 프로필로
원격 현황을 조회·관리할 수 있어야 한다. 소스 복원/실행은 불가능하다.
로컬 연결 프로필은 endpoint, project_id, credential_ref 등 비밀 아닌
설정만 보관하며 기존 host-local 인증정보 해석·리다이렉트 거부를 재사용한다.

```text
ISEKAI 협업 | 프로젝트 A | 사용자 philip | 관리자 | 3초 전 갱신
[요약] [내 작업] [인수함] [인계함] [작업자] [사용량] [기억 검색] [관리]

작업                     담당자 / CLI          소유권       실행 보고
인증 오류 수정            지민 / Claude         유효         실행 중
회귀 테스트               서연 / Codex          유효         승인 대기
배포 문서                 민수 / Kiro           만료         확인 지연

선택 상세
인계: 지민 -> 서연, 민수 | 확인: 1/2 | 작업: 구현 1건, 검증 1건
서버 체크포인트: 14:32 | 실행 보고: 14:33 | 소유권 만료: 14:36
인계에 고정된 저장본: v4 | 더 최신 체크포인트: v5 (자동 교체 안 됨)

[관리]
인수자 정책 | 체크포인트 복구 | 작업 재배정 | 정책 변경 이력
인계자: 지민   인수자: [서연] [민수]   예비: [수현]
[변경 미리보기] [확인 후 저장] [취소]
```

### 화면별 책임

| 화면 | 일반 사용자 | 프로젝트 관리자 |
| --- | --- | --- |
| 요약/작업자 | 자신이 접근 가능한 작업과 세션, 범위 표시 | 해당 프로젝트 전체 협업 현황 |
| idle 상세 | 관측된 세션별 대기/실행·승인·지연 구분; 사용자별 범위 내 집계 | 동일 판정 + 프로젝트 관측 정책 편집; 자동 이탈/근태 판정 아님 |
| 사용량 | 내 프로젝트별 기간/작업/세션/CLI/모델 토큰; 보고·추정·누락 분리 | 해당 프로젝트 사용자별 집계·사용량 알림 정책; 청구/구독 한도 아님 |
| 내 작업 | 자신의 소유/배정 작업; 같은 사용자 다른 세션도 구분 | 자신의 작업; 다른 사람 소유권을 가장하지 않음 |
| 인수함/인계함 | 독립 전달·확인 상태, 내가 보낸 bundle 목록 | 프로젝트 내 bundle 검색·분담 상태 |
| 기억 검색 | 기존 승인된 프로젝트 경험 검색·명시적 상세 조회 | 동일 검색; 기존 경험 제안 검토·승인/거절 폼 |
| 인수자 정책 | 자신의 적용 정책 조회 | 기본/인계자별 1:N 및 예비 대상자 편집 |
| 체크포인트 복구 | 내 저장본에서 허용된 대상에게 인계 발행 | 이탈한 사용자 저장본 조회·복구 발행 |
| 작업 재배정 | 불가; 소유 작업의 명시적 반납은 별개 | 분담·인수자 변경, 조건부 긴급 재배정 |
| 감사/삭제 | 원래 허용된 상태만 조회 | 기존 감사 이력, 명시적 체크포인트 본문 삭제 |

관리 정책 폼은 M8의 모든 설정을 포함한다: 활성화, 기본 수신자/예비,
인계자별 규칙, 보존기간, 작업 임대 시간, 체크포인트 주기·용량·경로,
긴급 인수 허용 여부. 권한 없는 항목은 숨기거나 사유와 함께 비활성화한다.
eligible user 목록은 사용자 디렉터리가 아니다. 토큰 발급·회수, 실제 회원
가입/조직 관리, 글로벌 서버 설정 변경은 기존 서버 운영 경계에 남긴다.
새 토큰 관리 API나 전체 Memory/Skill 관리 UI를 이번에 암묵적으로 만들지 않는다.

첫 화면은 표 위주로, 80x24에서는 상세를 별도 화면으로 분리한다.
120x36 이상에서는 목록/상세 동시 표시. 키보드만으로 모든 폼을 완료할 수
있어야 하고, 마우스는 보조다. 한글 이름·긴 제목·크기 변경·색상 없는
터미널에서도 상태와 확인 버튼을 읽을 수 있어야 한다.
표 선택과 Enter 상세 열기는 ack/claim/renew를 실행하지 않는다.

## 3. 재사용할 구현과 부족한 계약

현재 구현:

- Memory 82 tools: 변경 feed/prune 2개 + usage 7개 + presence 8개 + M9-1 overview/list 2개 + 개인 continuity inbox, bundle별 status, checkpoint 목록,
  관리자 policy/members/publish/reassign/history/forget.
- 기존 memory_search/read, experience_list/review 등 지식 조회·검토 도구.
- Core continuity의 capture/inspect/ack/claim/prepare/renew/release.
- 기존 M7 sent inbox는 legacy handoff용이다. M8 bundle 인계함과 같지 않다.

초기 설계의 추가 요구 (구현 결과는 9절과 완료 검증표 참조):

1. 개인/관리자 통합 현황, M8 보낸 bundle, 작업·세션 목록의 유한 조회.
2. 서버가 확인한 사용자/권한/지원 기능, 응답 범위·신선도 표시.
3. Core 실행 세션의 등록·상태 보고·종료와 유실/지연 판정.
   사용자별 idle은 [idle 상세 설계](memory-presence-idle.md)에 따라 집계한다.
4. [토큰 사용량 계약](memory-token-usage.md): host별 수집 지원 확인, 실제 보고와
   추정 분리, 캐시/부모-자식 중복 방지, 사용자·작업별 권한 집계.
5. TUI 폼, 충돌·응답 유실 복구, 관리자 승인 이력.
6. 이후 내구성 있는 변경 이벤트/재연결 복구. 기존 inbox cursor는
   이벤트 cursor가 아니며 재사용해서는 안 된다.

## 4. 구성과 코드 소유 경계

```text
Claude / Codex / Kiro -> 각자의 Core 실행 -> Memory에 상태/저장 보고
                                |
사용자·관리자 TUI -> Core의 Memory 클라이언트 -> Memory 조회/관리 서비스
         |
         +-> 명시적인 로컬 작업 요청 -> Core 검증·승인 경로
```

| 저장소/예정 위치 | 책임 |
| --- | --- |
| Memory: continuity/overview.py, presence.py, events.py | 권한별 읽기 모델, 세션 상태, 변경 이벤트 |
| Memory: continuity/usage.py 및 저장 계층 | 사용량 receipt/집계/알림 정책; presence와 별도 계약 |
| Memory: continuity/tools.py, server/auth.py, main.py | 추가 MCP 계약·인증·디스패치; 기존 서비스 재사용 |
| Memory: migrations/versions/011_* 이후 | 필요한 additive 테이블/인덱스/가드; 번호는 구현 시 확정 |
| Core: memory/overview.py, presence.py | bounded HTTP client, 상태 보고·응답 검증 |
| Core: host/ parsers, memory/usage.py | 구조화 usage 정규화, 최소 메타데이터 보고·재전송; runtime protocol로 연결 |
| Core: cli/console/ | TUI app/screens/forms/presenters; SQL·Core State 직접 조작 금지 |
| Core: kernel/ 및 기존 runtime service protocol | 실행 생명주기 연결, 안전한 사용자 명령 경계 |
| Core: pyproject.toml | 선택 의존성 console extra, 기존 headless 설치 유지 |

새 top-level feature를 불필요하게 만들지 않는다. 기존 cli -> memory/kernel,
memory -> infrastructure/runtime 경계를 유지한다. execution에서 memory를
직접 import하지 않는다. TUI는 PostgreSQL에 직접 접속하지 않는다.
관찰 전용 시작이 Kernel State 생성/마이그레이션이나 작업 실행을 유발하지
않도록 remote metadata 연결과 로컬 실행용 Kernel 경로를 분리한다.

TUI 후보는 **Python Textual**. 기존 Python 코드·pytest를 활용하고, 선택
의존성으로 지연 import한다. headless 키 입력/화면 크기 테스트와 백그라운드
조회 worker를 제공한다. 버전 고정 및 Python 3.11 호환성은 구현 첫 단계에서
검증하며 이 준비 단계에서는 설치하지 않는다.
[Textual testing](https://textual.textualize.io/guide/testing/),
[Textual workers](https://textual.textualize.io/guide/workers/).

## 5. 통합 조회 API 초안

overview/list는 [M9-1 상세 계약](memory-collaboration-read-model.md)으로 구현됐다.
presence는 [구현 계약](memory-presence-runtime.md), usage는 [v1 계약](memory-usage-runtime.md)을 따른다.
events 도구는 아직 **제안**이다.

- memory_collaboration_overview: 인증된 identity, 허용 actions, 지원 기능,
  권한 내 카운트, observed_at, 조회 범위, 각 데이터 영역 상태.
- memory_collaboration_list: view=work/inbox/sent/checkpoints (sessions는 후속),
  project_id, 최대 분류, limit(기본 20/최대 50), scoped cursor, 유한 필터.
- memory_presence_register/heartbeat/end: 인증된 actor의 상태 보고 세션만 조작.
- memory_presence_policy_get/set: 별도 versioned 관측 정책 제안; admin 쓰기,
  기존 strict M8 정책과 분리해 heartbeat/stale/idle 임계값을 관리.
- memory_usage_report/summary/list: 인증된 작업 소비 보고와 권한별 유한 집계.
- memory_usage_policy_get/set: 별도 versioned 보존/알림 정책; 알림은 자동 중단 아님.
- memory_collaboration_events: M9 후반의 별도 지속 이벤트 cursor/catch-up 계약.

inbox/status 등 M8 도구는 그대로 유지한다. 조회별 DTO를 서비스에서 구성하고
TUI가 50개 행을 그리기 위해 50번 status를 호출하는 N+1 구조를 피한다.
상세 본문은 사용자가 열 때 별도 권한 검사 후 조회한다.

공통 응답은 contract_version, project_id, actor_id, observed_at, coverage,
cache_policy:no_store를 포함한다. capabilities/actions는 서버 권한에서
계산하며 신뢰할 수 없는 UI 플래그로 권한을 넓히지 않는다.
분류 필터는 상한을 낮출 뿐 새로운 보안 등급 권한을 만들지 않는다.
counts도 행과 동일한 프로젝트/사용자/분류 가시성 필터를 적용한다.

기본 visibility:
- 일반 사용자는 기존 M8에서 허용되는 자신이 발행했거나 현재 수신자인
  bundle과 연관 작업 메타데이터, 자신의 세션만 조회한다.
- 다른 사람의 세션은 해당 공개 가능 bundle/work 연결이 확인된 부분만
  보이며, 다른 프로젝트·개인 작업의 세션 정보는 노출하지 않는다.
- admin은 자기 프로젝트 전체. 프로젝트 간 전역 목록이나 admin 자동
  위임은 없다. 여러 프로젝트 프로필은 각각의 인증정보로 따로 연결한다.
- 일반 사용자에게 프로젝트 전체 관찰 권한이 필요하면 별도 정책/권한
  설계를 선행한다. read scope를 이유로 기존 가시성을 넓히지 않는다.

서버에서 유효한 lease인지 계산하여 raw state=claimed와 분리한 effective
상태를 반환한다. retained/expired/forgotten/revoked도 별도로 드러낸다.
마지막 페이지에 갱신된 행을 놓치지 않도록 매 poll은 첫 페이지에서 시작한다.
목록은 live view이며 snapshot 일관성을 보장하지 않는다고 명시한다.
카운트가 예산 내 계산되지 않으면 partial/unknown과 범위를 표시하고
페이지 길이를 전체 작업 수처럼 보여주지 않는다.

## 6. 작업자 현황: 소유권 / 실행 보고 / 저장 확인 분리

[세션별·사용자별 idle 상세 계약](memory-presence-idle.md)을 따른다.
idle은 관측된 Core 작업 대기이며 사람의 부재·PC 미사용·업무 가능 여부가 아니다.
실행/승인 대기와 보고 지연을 별도로 표시하고, 일부 세션을 모르면 사용자
전체를 idle로 확정하지 않는다. 초기 기준은 연속 대기 5분(관리자 설정 가능)이다.
작업 중 무출력·자동 저장·화면 갱신을 사람의 활동 또는 idle 근거로 쓰지 않는다.

presence 기록의 후보 필드:
project_id, actor_id(서버 인증), server_session_id, client_instance_id,
host_kind(claude/codex/kiro/unknown), 선택적 로컬 unit/공유 work 연결,
run_state, monotonic_sequence, last_seen_at(서버 시간), ended_at.
idle 상세 설계에서 observation_scope, 활동 sequence, 서버 idle_since_at,
정책 버전과 사용자별 집계 완전성을 추가 정의한다.

- 한 사용자도 여러 CLI·장치·세션을 가질 수 있다. user_id 하나로 덮어쓰지 않는다.
- 세션 등록 시 소유자 전용 비밀 capability를 결박하고 원시 비밀값은
  목록에 내보내지 않는다. 등록 재시도와 seq 중복은 같은 세션으로 수렴한다.
- 중복 heartbeat가 last_seen을 새 활동으로 연장하거나, 늦은 heartbeat가
  ended 세션을 되살리지 않게 한다. 서버 인증/프로젝트/세션 소유를 매번 검증한다.
- 기본 목표: 보고 15초, 60초 미수신 시 stale. 서버 설정과 측정 결과로
  조정 가능하며 사용자 이탈/사람의 온라인 여부나 실행 사실의 증명이 아니다.
- 실행 상태는 idle/running/waiting_approval/blocked/ended 등의 **Core 보고**다.
  신선도 fresh/stale/unknown는 별도 축이다. CPU 사용량으로 추측하지 않는다.
- 원격 work와 연결은 같은 프로젝트의 합법적인 관계를 검사한다.
  소유권은 실제 lease를 조회해 결정한다. 임의 reported work ID로 타인 작업을
  실행 중이거나 자신이 소유한다고 표시하지 않는다.
- heartbeat에는 코드·대화·명령·로컬 절대 경로·원시 토큰을 포함하지 않는다.
- 서버가 검증할 수 있는 최신 checkpoint ID를 연결한다. 더 최근 저장본이
  존재해도 이미 발행된 인계의 원본을 자동 교체하지 않는다.
- Core를 통하지 않은 CLI 작업과 hook이 제공하지 않는 승인 상태는 unknown.
  알 수 없는 필드를 가짜 running/100% 완료/진행률로 채우지 않는다.
- TUI 자체의 poll은 작업 heartbeat나 lease 갱신이 아니다.
  TUI 종료가 Core 작업의 상태 보고·저장·소유권을 중단하지 않아야 한다.
- M8의 worker checkpoint guard만으로 CLI 입력 대기를 관측할 수 없다.
  장기 실행 Core observer를 별도로 설계하며 단발 명령 종료 후에는 ended/
  stale로 표시한다. TUI만 켜서 사용자 idle을 추정하지 않는다.
- 최초에는 명시적 opt-in. SQLite 객체는 배경 스레드로 넘기지 않고,
  실패는 로컬 기록하되 Memory에 저장/보고 성공으로 표시하지 않는다.
- 세션 수·요청 빈도·본문 크기를 제한하고, 오래된 presence 보존/정리 정책을
  구현·검증한다. heartbeat마다 영구 감사 이벤트를 쌓지 않는다.

## 7. 관리자 TUI 변경 처리

기존 서비스 호출을 조합하며 UI만의 쓰기/검증 규칙을 만들지 않는다.

```text
대상 선택 -> 현재 버전과 정책 읽기 -> 폼 편집
 -> 변경 전/후 및 영향 범위 미리보기 -> 이유·사용자 확인
 -> 기존 Memory tool 호출 -> 서버 receipt 확인 -> 화면 재조회
```

- 관리자 모드는 명시적으로 켜고 계속 표시한다. 일반 조회와 token 역할을
  혼동하지 않는다. watch --manage만으로 관리자 권한을 부여하지 않는다.
- 인수자 폼은 기존 eligible identities에서 복수 선택, sender override /
  기본값 구분, 자기 인수·중복·예비 중복 금지와 원래 제한을 안내한다.
- 정책은 전체 replacement와 expected_version을 보존한다. 다른 관리자가
  저장하면 자동 덮어쓰지 않고 차이를 표시하여 다시 검토한다.
- 재배정은 모든 기존 unit의 expected_generations, bundle expected_version,
  실제 변경할 수신자·분담을 고정한다. 수정하지 않은 작업의 claim을 유지한다.
- 긴급 재배정은 허용 정책, takeover_unit_keys, 이유, 실행 중 프로세스는
  중지되지 않는다는 확인을 전부 받는다. 단일 단축키로 즉시 실행하지 않는다.
- forget는 삭제 대상/의존 인계 영향, 복구 불가한 본문 삭제임을 표시하고
  대상 ID 확인을 요구한다. 실제 사용자 데이터로 시연하지 않는다.
- 지식 검토는 기존 experience list/review를 사용하고 현재 버전·근거를
  확인한다. 인계 완료나 체크포인트만으로 지식을 자동 승인하지 않는다.
- 사용량은 [별도 계약](memory-token-usage.md)에 따라 사용자별/프로젝트별 알림
  기준과 수집/보존 정책을 관리한다. 관리자 설정만으로 기기 수집을 켜지 않으며,
  임계치 초과로 작업을 자동 중단·재배정하거나 실제 구독 잔여량을 추측하지 않는다.
- idempotency key와 정확한 요청을 소유자 전용 pending receipt에 저장한다.
  응답 유실은 실패로 단정하지 않고 결과 미확정으로 표시한다. 명시적
  재시도는 동일 요청/키를 사용하고, 서버 상태와 함께 성공 여부를 확인한다.
  취소는 이미 전송된 서버 작업을 되돌리지 않는다. pending에는 인증 토큰,
  원문 snapshot을 보관하지 않으며 최소 메타데이터 보존 정책을 둔다.
- 새 actor/project로 전환하면 이전 작업의 pending/캐시를 섞지 않는다.
  401/403 또는 권한 철회 확인 시 민감 화면을 지우고 쓰기를 중단한다.
- 관리자도 타인의 ack/claim을 가장할 수 없다. 관리자 복구는
  checkpoint read/publish/reassign을 통해서만 수행한다.

## 8. 갱신·보안·로컬 실행

관찰은 기본 5초 poll(사용자 선택 3~30초), jitter, 단일 in-flight, 유한
응답 크기/요청 시간, 오류 시 지수 backoff를 사용한다. 느린 과거 응답이
새 화면/프로젝트/필터를 덮어쓰지 않게 요청 세대 ID를 검증한다.
현재 Memory client의 socket timeout이 전체 작업 deadline과 같지 않다는
점을 고려하여 poll queue가 쌓이지 않게 한다.
네트워크 조회를 렌더링 루프에서 blocking 실행하지 않는다.

연결 끊김은 마지막 확인 시각과 stale로 표시하고, 기록을 최신이라고
보이지 않는다. 본문·스냅샷·토큰은 자동 조회/디스크 캐시/터미널 로그에
출력하지 않는다. 목록도 서버의 no_store 계약 아래 현재 표시용 메모리에만
둔다. 인증 철회/프로필 전환 시 지우며 다시 권한을 확인한다.
미신뢰 제목/사용자명/오류에서 ANSI/OSC·제어문자와 Rich markup을 제거하거나
문자 그대로 렌더링한다. 원격 문자열을 shell command에 보간하지 않는다.

M9 후반의 변경 feed는 목록 cursor와 분리한다. 이벤트 저장은 변경과
원자적이어야 하고 cursor 순서가 commit 가시성을 건너뛰지 않게 한다.
권한 변경/취소/종료도 포착하고, reconnect에서는 유한 catch-up과 gap 시
전체 refresh를 제공한다. 소스 본문 대신 최소 식별자/버전만 전달한다.
초기 poll 화면의 최근 목록을 완전한 감사/알림 이력이라고 부르지 않는다.

로컬 인수/준비/반납은 선택한 ID와 generation을 Core의 기존 사용자 명령
경로로 넘긴다. 같은 actor여도 다른 세션 소유 claim은 가져오지 않는다.
watch가 claim 파일을 임의로 열어 갱신하거나 복원을 자동 실행하지 않는다.
에이전트가 MCP로 호출할 때 기존 activation/caller 검증을 유지한다.
자동 lease 갱신은 별도 opt-in 작업 세션 제어기의 책임으로 구현하고
TUI가 켜져 있다는 이유로 lease를 유지하지 않는다.
추가 실행·승인은 기존 CLI에 남긴다. TUI에서 원격 shell을 실행하지 않는다.

## 9. 단계별 구현 및 완료 조건

| 단계 | 변경 범위 | 완료 조건 |
| --- | --- | --- |
| M9-0 준비 | 이 문서·진행표 | 화면/권한/서버-Core 경계 및 아래 테스트 확정 |
| M9-1 조회 계약 (로컬 구현·검증) | Memory overview/list, Core bounded read client | 내/보낸/받은/관리자 범위, 분류·페이지·카운트·만료 처리; [구현 계약](memory-collaboration-read-model.md) |
| M9-2 실행 관측 | presence schema/service, Core session 보고 | 3종 CLI 식별/unknown, 동일 사용자 복수 세션, 오래된 보고 차단, opt-in/종료/정리 |
| M9-2a idle 판정 | 관측 정책, 순수 판정 함수, 서버 집계 | 실행·승인·대기·지연 구분, 사용자별 최솟값 기간, 단절/partial 오판 방지; [판정표](memory-presence-idle.md) |
| M9-2b 토큰 사용량 | host usage DTO/parser, receipt/집계/정책 | 보고·추정·미지원 구분, 캐시/누적/부모-자식 중복 방지, 권한·기간 집계; [수용표](memory-token-usage.md) |
| M9-3 공통 TUI (로컬 구현·검증) | console extra, watch/profile, 메타데이터·세션·사용량 집계/필터 연결 | 단일 명령·키보드·80x24/120x36·한글·단절/철회 검증, Python 3.11 wheel 검증 |
| M9-4 관리자 TUI (로컬 구현·검증) | 정책·1:N·체크포인트 복구·재배정·감사·forget·관측/사용량·경험 검토 폼 | 웹 없이 핵심 협업 시나리오; 미리보기·확인·충돌·응답 유실 회복 |
| M9-5 사용자 작업 연결 | 인수/준비/인계/반납, 작업 세션 lease 제어 | 기존 검증·승인 유지, 소유 세션 구분, TUI 종료와 worker 분리 |
| M9-6 알림·운영 검증 | durable feed/catch-up, 마이그레이션·패키징·E2E | 재접속 유실 복구·권한 철회·데이터 보존, 아래 수용 시나리오 통과 |

M9-3 관찰 화면만으로 M9 전체를 완료 처리하지 않는다. **관리자 TUI는
필수 산출물**이며 웹 구현으로 대신하지 않는다. 외부 connector와 완전한
조직 회원 관리/자동 이탈 판정은 M10 또는 별도 범위로 남긴다.

### 수용 테스트

아래 완료는 [최종 검증표](memory-m9-acceptance.md)의 지원 범위·합성 fixture 기준이다.
실제 구독 CLI 연결·운영 부하 인증을 포함하지 않는다.

- [x] 일반 사용자와 관리자에게 동일 바이너리가 서로 다른 허용 메뉴/범위를 제공.
- [x] 관리자 정책이 아직 없어도 프로필 연결·초기 정책 생성 폼 진입 가능.
- [x] A 인계가 B/C에게 독립 도착; B 확인이 C 상태를 소비하지 않음.
- [x] 관리자가 TUI만으로 1:N/예비/모든 M8 정책 수정 및 checkpoint 복구 발행.
- [x] 두 관리자 동시 편집, 오래된 generation, 응답 유실/재시도에 중복 변경 없음.
- [x] 긴급 재배정의 사유·영향 확인·서버 감사, 실행 프로세스 중지로 오표시하지 않음.
- [x] 같은 사용자 Claude/Codex/Kiro 세션이 구분됨. lease/실행 보고/저장 시각 각각 표시.
- [x] 정상 종료, 강제 종료, 네트워크 단절, 지연 heartbeat/중복/순서 역전 처리.
- [x] [idle 판정표](memory-presence-idle.md)의 경계값·복수 세션·단절·권한 범위·정책 변경 시나리오 통과.
- [x] [토큰 사용량 수용표](memory-token-usage.md)의 실제 보고/추정/누락, 캐시·누적 중복, 재시도·시간·권한·알림 검증.
- [x] CLI별 실제 수집 지원과 갱신 단위를 표시; final-only/미수집을 실시간 0으로 표현하지 않음.
- [x] 새 로그인 없이 기존 토큰 프로필로 사용자/관리자 TUI를 사용; 인증 실패는 차단.
- [x] 관찰 화면 열기/새로고침/닫기가 ack/claim/renew/capture를 일으키지 않음.
- [x] 타 사용자/프로젝트 필터·카운트·cursor·세션 ID 위조와 철회 후 읽기 차단.
- [x] TUI 렌더링 injection, 토큰/본문 로그 유출, 잘못된 프로필 캐시 재사용 방지.
- [x] 키보드만으로 정책·재배정 완료; 80x24/120x36, 한글/긴 값/resize/snapshot 테스트.
- [x] 최대 페이지·응답량·세션 수에서 poll 폭주/N+1/이벤트 폭증 없음.
- [x] 별도 합성 데이터로 real HTTP, Core 3종 host fixture, 관리자/인수자 TUI E2E.
- [x] 기존 Memory/Core 회귀, additive migration 보존/rollback 정책, wheel/console extra 검증.
- [x] feed 중단/재시작/보존기간 초과 및 권한 취소 후 catch-up/전체 refresh 검증.
- [x] 합성 local fixture를 실제 구독 CLI 연결 성공으로 표현하지 않음.
      실 CLI smoke는 설치 버전·계정·권한이 준비된 명시적 opt-in 테스트로 별도 기록.

## 10. 실제 운영 전 체크

1. 운영 데이터 백업 후 의존성을 설치하고 Memory에서 `python -m alembic upgrade head`를
   명시적으로 실행한다. 현재 코드에서는 schema 020과 89 tools의 readiness를 확인한다. 이 작업에서 운영 DB는 변경하지 않았다.
2. Core는 `python -m pip install -e '.[console]'`로 선택 TUI 의존성을 설치한다.
   실제 경로의 Python을 사용한다. 이전 디렉터리로 이동하기 전 만들어진 실행 스크립트의 shebang은 별도 정비 대상이다.
3. 사용자별 기존 credential_ref와 프로젝트 권한을 설정한다. 신원은 Git author가 아니다.
4. 관찰부터 시작한다. 작업 모드는 로컬 continuity opt-in, 관측/토큰 수집은 각각 별도 opt-in이 필요하다.
5. 실제 CLI smoke는 계정·실행 허용을 받은 뒤 별도 수행한다. Claude/Kiro 토큰은 현재 unsupported다.
