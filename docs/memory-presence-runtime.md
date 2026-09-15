# M9 관측 API와 Core worker 연결

2026-09-14 추가: [실제 Core controller lifecycle](memory-controller-runtime.md)을 연결하고 검증했다.
현재 전체 스키마는 013, 도구는 82개다. 최종 상태는 [M9 검증표](memory-m9-acceptance.md)를 따른다. 아래 011/73개 및 controller 미구현 설명은 최초 worker 단계의 기록이다.

상태: 로컬 구현·검증, 2026-09-11. [idle 의미·판정 설계](memory-presence-idle.md)를 구현하는
첫 수집 계층이다. M9 전체 완료나 실제 CLI 계정 검증을 뜻하지 않는다.

## 구현 범위

Memory schema 011은 관측 정책과 세션 테이블을 추가한다. M8 체크포인트·전달·
ack·작업 lease는 수정하지 않는다. 카탈로그는 73개 도구다.

| 도구 | 권한 | 용도 |
| --- | --- | --- |
| memory_presence_policy_get | read | 정책·버전 조회, 미설정은 수집 비활성 |
| memory_presence_policy_set | admin | 전체 정책 교체, expected_version·이유·멱등 receipt |
| memory_presence_register | write | 내 Core 세션 등록, 재시도는 last_seen을 연장하지 않음 |
| memory_presence_heartbeat | write | 내 세션의 최신 관측, 전송/상태 sequence 검사 |
| memory_presence_end | write | 내 세션 정상 종료, 종료 후 재보고 거부 |
| memory_presence_list | read | 세션별 상태·신선도·idle 메타데이터 |
| memory_presence_users | read | 목록 한 페이지가 아닌 권한 범위 전체 열린 세션으로 집계 |
| memory_presence_prune | admin | 보존 만료 기록의 관측 메타데이터 정리, 재생 방지 표식 유지 |

모든 요청은 project_id와 기존 인증이 필요하다. mine은 자신의 세션만,
project는 해당 프로젝트 관리자만 조회한다. 다른 사람의 공유 작업에 연결된
세션을 일반 사용자에게 공개하는 확대 정책은 아직 구현하지 않았다.

등록은 인증 actor + 프로젝트 + client_instance_id와 세션 비밀 capability에
묶인다. 서버는 capability 원문을 저장하지 않으며 일반 조회는 그 해시,
등록 fingerprint, instance 식별자도 반환하지 않는다. 관리자는 다른 사용자의
등록/보고/종료를 가장할 수 없다.

## 시간·재시도·소유권

- 서버가 last_seen_at, state_since_at, idle_since_at을 기록한다.
- 같은 sequence와 같은 보고는 기존 receipt만 반환한다. 과거 sequence,
  같은 sequence의 다른 내용, 종료된 세션의 보고는 거부한다.
- 상태 sequence는 실행 상태·관측 범위·활성 작업 수·공유 작업 연결의 실제
  변경에만 증가한다. 동일 UUID의 대소문자는 활동이 아니다.
- 자동 저장·checkpoint 연결 갱신·단순 heartbeat는 idle 시작을 바꾸지 않는다.
  stale 기준 이상의 단절 후 복귀는 새 연속 관측 구간을 시작한다.
- 현재 할당과 유효한 전달 관계가 있는 공유 work만 연결할 수 있다.
  연결은 claim이 아니며 실제 실행을 증명하지도 않는다. lease는 별도다.
- 연결된 checkpoint는 자신의 유효한 저장본이어야 한다. 연결된 데이터의
  분류 이상으로 세션 분류를 높이고, 나중에 낮춰서 노출할 수 없다.
- 부모 세션은 같은 사용자·프로젝트의 세션만 허용한다. Core worker가 실제
  controller 부모와 자동 연결되는 경로는 후속 작업이다.

조회는 읽기 전용 repeatable-read와 유한 시간 예산을 사용한다. 사용자는
권한 범위 전체 열린 세션을 집계하며, 열린 세션이 없으면 최근 종료 기록을
사용한다. 모두 idle이어야 사용자 idle이고, 함께 대기한 가장 짧은 시간을
반환한다. running + stale은 실행 중 표시와 불확실성을 함께 유지한다.
사람의 부재·퇴근·업무 가능 여부를 추론하지 않는다.

## 정책과 운영 제한

기본 enabled=false, heartbeat 15초, stale 60초, idle 300초, 보존 168시간.
정책 범위는 각각 10–60초, 45–300초, 60–3600초, 1–720시간이며 stale은
heartbeat의 3배 이상이어야 한다. 임계값 변경은 새 사용자 활동이 아니다.

등록은 사용자당 열린 세션 64개, 프로젝트당 미정리 세션 10,000개,
사용자당 분당 10개로 제한한다. 조회 페이지는 최대 50개, 사용자 집계의
내부 세션 예산은 10,000개다. 초과하면 불완전함을 표시하며 idle로 확정하지 않는다.
상태 보고 주기 준수와 별도의 요청 빈도 제한·부하 측정은 후속 운영 검증 대상이다.

prune은 명시적 관리자 요청으로 최대 500개를 처리한다. host/state/작업 연결
등 관측 메타데이터를 지우지만 프로젝트·actor·instance·sequence·등록 digest·
시각 등의 최소 재생 방지 기록은 남긴다. 완전한 사용자 정보 삭제 API가 아니다.
이 표식은 늦은 보고나 옛 등록 재전송이 새 활동이 되는 것을 막는다.
heartbeat마다 감사 기록을 추가하지 않으며, 상태 전환·재연결·관리 작업을 기록한다.

011은 M8 데이터가 있는 DB에도 추가할 수 있다. presence가 빈 경우 010으로
되돌릴 수 있지만 정책/세션 이력이 있으면 다운그레이드를 거부한다. 종료·정리
기록도 예외가 아니다. 운영 DB에 적용하기 전에는 백업·보존 정책을 확인해야 한다.
이번 구현에서는 전용 합성 DB만 변경했다.

## Core 연동과 남은 수집 범위

기존 integrations.memory 설정에 presence_enabled=true를 명시하고,
서버 관측 정책도 enabled=true여야 보고한다. 두 opt-in은 독립이다.
이 문서는 설정 예시이며 실제 프로젝트에 적용하지 않았다.

현재 자동 연결은 실제 worker adapter 호출의 시작/종료다. 승인된 worker가
실행되는 동안 running을 보고하고 종료 시 end를 보낸다. TUI와 독립된 수명이며,
SQLite/Kernel 객체를 배경 스레드에 넘기지 않는다. 로컬 진단은
.isekai/presence/worker-<hash>.json에 비밀 없는 결과 코드만 0600으로 기록한다.

PresenceReporter는 구조화된 controller/worker 관측을 전달할 수 있지만,
장기 실행 실제 MCP controller의 입력 대기/승인 상태 연결은 아직 미구현이다.
단위·HTTP 테스트의 controller idle/approval 보고는 합성 입력이다.
CLI 외부 작업·입력 없음·계정 전체 활동을 관측한다고 주장하지 않는다.
Kiro/Codex/Claude라는 host_kind도 보고자의 선언이지 CLI 실행의 독립 증명이 아니다.

네트워크 실패 시 최신 상태만 남기며, 오프라인 heartbeat를 쌓아 재생하지 않는다.
응답 유실 후 동일 등록으로 서버의 확정 sequence/state fingerprint를 확인하고
현재 관측을 보낸다. 종료 응답이 없으면 end_unconfirmed/end_pending을 기록한다.
전송은 3초/16 KiB로 제한하며, 인증/계약 오류는 자동 익명 전환 없이 중단한다.
수집 비활성은 스레드·네트워크·진단 파일을 만들지 않는다.

PresenceClient는 Kernel/SQLite 없이 policy/listing(sessions/users)을 읽는다.
프로젝트·actor·분류·필터·페이지 크기·상태/카운트 일관성을 검증한다.
5초/512 KiB 한도, 캐시 없음, 인증 철회 시 과거 성공값 재사용 없음.
overview의 presence/idle capability=true는 별도 조회 API 지원만 뜻한다.
telemetry는 separate_query/use_presence_tools/null이며 실제 수집 성공은 별도다.
token_usage는 아직 unavailable/not_implemented/null이다.

## 검증과 다음 단계

- Memory 순수 idle 45개, 입력/권한 21개, PostgreSQL 12개 시나리오.
- Core reporter 27개, 읽기 client 57개 시나리오 및 기존 overview 회귀.
- 실제 HTTP Core reporter/reader → Memory, 2명 독립 actor, 대기/승인/정상 종료.
- 실제 stdio 카탈로그 73개와 기존 M0–M8 및 M9 조회 회귀.
- 별도 빈 DB의 M8 데이터 보존, 011 업/다운그레이드, 이력 존재 시 거부 검증.

TUI 화면·관리 폼·controller lifecycle·토큰 ledger·내구성 이벤트는 남아 있다.
실제 CLI 구독 사용·운영 배포·프로젝트 활성화·커밋·푸시는 수행하지 않았다.
전체 테스트 수와 정확한 실행 범위는 [작업 기록](memory-expansion-progress.md)을 따른다.
