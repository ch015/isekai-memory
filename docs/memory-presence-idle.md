# M9 TUI: 세션 관측과 사용자별 idle 판정

상태: **순수 판정 + 저장/API + Core worker/controller 수집·TUI 조회·관리자 관측 정책 폼 구현·합성 검증**. 2026-09-14.
[장기 controller 연결·관측 한계](memory-controller-runtime.md)를 함께 확인한다.
실제 도구·제한·검증 범위는 [관측 runtime 계약](memory-presence-runtime.md)을 따른다.
아래 예정/제안 내용 중 구현되지 않은 부분은 이 상태 요약과 구분한다.
[협업 TUI 준비서](memory-collaboration-tui.md)의 상태 표시·관리 정책을 구체화한다.
새 로그인과 Nunchi 인증 연동은 후속으로 보류한다. 기존 Memory 프로젝트 토큰과
credential_ref를 사용하며, 신원·권한 검증을 생략하는 익명 모드로 바꾸지 않는다.

## 1. idle의 의미

이 문서의 idle은 **관측 가능한 Core 세션이 살아 있으면서 작업을 하지 않고
대기하는 상태**다. 사람이 자리를 비웠는지, 업무를 하지 않는지, 새로운 일을
맡을 의사가 있는지, PC가 잠겼는지를 의미하지 않는다.

세션별로 판정하고 사용자별로 접어서 표시한다. 다음 네 축을 합치지 않는다.

| 축 | 값/예시 | 근거 |
| --- | --- | --- |
| 상태 보고 신선도 | fresh / stale / unknown / ended | 서버가 수신한 새로운 유효 보고와 정상 종료 |
| Core 실행 보고 | running / waiting_approval / blocked / idle / unknown | 관측 범위가 선언된 Core lifecycle observer |
| 작업 소유권 | 유효 / 만료 / 미보유 | 실제 Memory work lease와 서버 시각 |
| 복구 가능한 저장 | 마지막 확정 checkpoint, 인계에 고정된 버전 | 서버의 실제 저장 기록 |

heartbeat가 있어도 실행 보고를 관측할 수 없으면 실행 상태는 unknown이다.
파일 변경이 없거나 도구 호출이 뜸하다는 이유로 running을 idle로 바꾸지 않는다.
긴 테스트·모델 응답 대기·무출력 작업도 관측된 실행이 계속되면 running이다.
유효한 lease를 가진 idle과 실행 보고는 있지만 lease가 만료된 상태 모두 가능하다.

[토큰 사용량](memory-token-usage.md)은 별도 관측 축으로 함께 표시한다. 토큰 증가
없음을 idle 근거로 쓰지 않으며, 늦은 usage 보고·재전송이 현재 작업 활동이나
heartbeat를 가장하지 않도록 사용량 수집 시각과 presence 시각을 분리한다.

## 2. 정보 수집 경계

현재 M8의 checkpoint_session은 worker adapter 호출 전후의 저장 경로다.
그것만으로 CLI가 사용자 입력을 기다리는 시간까지 관측할 수는 없다.
M9에서는 TUI와 별개인, 명시적으로 켠 Core 세션 observer가 필요하다.

- 장기 실행 Core/controller 세션: 실제로 알고 있는 작업의 준비·실행·검증,
  승인 대기·막힘·대기·종료를 보고한다. 살아 있는 observer가 자신의 현재
  작업 집합이 비어 있음을 확인할 때만 idle을 보고할 수 있다.
- 여러 worker가 있으면 활성 작업 집합이 모두 끝나기 전에 idle로 바꾸지 않는다.
  DB에 남은 과거 RUNNING 문자열만으로 실행 중이라고 판정하지 않는다.
- 관측할 수 없는 CLI 외부 작업이나 승인 대기는 unknown. 세 CLI가 같은 hook을
  제공한다거나 모든 사용자의 입력 이벤트를 Core가 받는다고 가정하지 않는다.
- 단발성 Core 명령은 완료되면 세션 ended. 프로세스가 종료된 뒤 heartbeat를
  보내는 가짜 대기 세션을 만들지 않는다. 종료 보고 유실은 stale이 된다.
- TUI는 observer를 가장하지 않는다. TUI만 열려 있으면 별도 작업 세션은
  관측 없음으로 표시한다. TUI를 닫아도 실제 Core의 observer는 계속 동작한다.
- 부모 controller와 worker attempt는 관계로 연결해 같은 작업을 중복 집계하지
  않는다. 사용자가 보는 행은 관측 단위/세션 종류와 세션 식별자를 포함한다.
- OS 전체 키보드·마우스, 화면 포커스, 앱 사용 이력, 터미널 출력 스크래핑,
  CPU 사용량이나 개인 메시지를 수집하지 않는다.
- 사용자 입력 없음 시간은 baseline에서 제공하지 않는다. 후속 opt-in adapter가
  의미 있는 입력 이벤트를 실제로 제공할 때만 별도 필드로 표시할 수 있다.
  작업 idle과 사용자 미입력 시간을 같은 값으로 쓰지 않는다.

## 3. 보고 데이터와 시간 기준

추가할 최소 데이터 후보(서버 DTO 확정은 M9-1/M9-2):

- 프로젝트·인증된 actor, 세션 UUID, 재시작을 구분하는 instance/epoch,
  host_kind, session_kind, 선택적 parent_session_id.
- reported_state, observation_scope, state_observation_available,
  현재 관측 작업 연결과 active_work_count.
- 전송 sequence, 상태/작업 활동 sequence, 서버 수신 last_seen_at.
- 서버가 계산한 state_since_at, idle_since_at, freshness, idle_seconds,
  is_idle_threshold_reached, reason_code, observed_at, policy_version.
- 마지막 확정 checkpoint와 현재 인계 원본 버전. source body나 토큰은 제외.

reported_state/host_kind는 Core가 보고한 값이지 사람의 신원·실행 사실에 대한
독립 증명이 아니다. actor는 인증에서 가져오며, 원격 work 연결은 권한과
프로젝트 관계를 별도 검사한다.

heartbeat 전송 sequence와 작업 활동 sequence를 분리한다. 새 heartbeat는
last_seen_at을 갱신하지만, 다음 이벤트는 idle_since_at을 초기화하지 않는다:

- TUI의 조회·새로고침·검색·탭 전환.
- 자동 lease 갱신, checkpoint 저장, health check와 단순 상태 재전송.

idle 시작 시각은 연속 관측 구간에서 서버가 idle 전환을 처음 수락한 시각이다.
observer가 실제 작업 시작을 보고하면 idle_since_at을 지우고, 그 작업이 끝나
idle로 돌아오면 새로 시작한다. 이벤트를 보내지 않고 임의 타임스탬프만 바꾸어
idle 시간을 조작하지 못하게 한다.

서버 시각을 판정 기준으로 한다. 클라이언트 시각은 권한·소유권·idle 기준으로
신뢰하지 않는다. 같은 sequence의 중복 전송은 last_seen_at도 연장하지 않고,
더 낮은 sequence와 ended 세션의 늦은 보고는 되살리지 않는다.
heartbeat는 최신 관측만 전송하며 오프라인 보고를 durable queue에 쌓아 나중에
현재 활동처럼 재생하지 않는다. 체크포인트의 durable upload retry와 다르다.

연결이 stale 기준을 넘었다가 돌아오면 연속 idle 구간을 다시 시작한다.
단절 중에도 idle이었다고 가정하거나, 그 시간을 idle 기간에 더하지 않는다.
서버 관측 시간의 역행이 감지되면 duration을 unknown으로 하고 새 구간을 잡는다.
TUI는 응답 observed_at 기준으로 시간을 표시하고, 연결이 끊기면 기간의 증가를
멈춰 마지막 확인값임을 표시한다. 로컬 시계만으로 소유권을 유효하게 만들지 않는다.

## 4. 세션 상태 판정표

예정 기본값: heartbeat 15초, stale 기준 60초, idle 기준 5분.
실제 배포/활성화된 설정이나 즉시 갱신 SLA가 아니다.

| 우선 판정 | 표시 | idle 여부 |
| --- | --- | --- |
| 정상 종료 확인 | 종료 | 아니오 |
| 등록/상태 관측 근거 없음 | 관측 없음 / 상태 미확인 | 판정 불가 |
| 마지막 유효 보고로부터 60초 이상 | 확인 지연 + 마지막 실행 보고 | 판정 불가 |
| fresh + running | 작업 중 | 아니오 |
| fresh + waiting_approval | 승인 대기 + 대기 시간 | 아니오 |
| fresh + blocked | 막힘 + 허용된 사유 | 아니오 |
| fresh + idle, 연속 관측 5분 미만 | 대기 2분 | 기준 미도달 |
| fresh + idle, 연속 관측 5분 이상 | idle 8분 | 예 |
| fresh + unknown/불완전 관측 | 상태 미확인 | 판정 불가 |

stale은 네트워크·프로세스 장애 후보이지 사용자 이탈 확정이 아니다.
자동 재배정·강제 lease 회수·토큰 폐기·완료 처리를 유발하지 않는다.
승인 대기는 아무리 길어도 idle로 치환하지 않는다.

idle/stale 임계치 통과는 서버 시각으로 계산하는 표시 상태다. 조회가 이를
DB에 기록하는 쓰기를 수행하지 않는다. 초기 TUI는 poll마다 재평가한다.
모든 시간 경과를 durable event로 보장하려면 별도 스케줄러/이벤트 계약이
필요하며, 일반 변경 feed만으로 타이머 이벤트도 생긴다고 가정하지 않는다.

## 5. 사용자별 집계

집계 키는 project_id + 인증된 actor_id. 조회 권한/분류/필터 내 세션만 사용한다.
표 제목에 **이 프로젝트에서 관측된 세션 기준**을 항상 표시한다. 다른 프로젝트,
숨겨진 세션 또는 Core 외부 작업까지 포함한 사람 전체의 상태라고 표현하지 않는다.

1. 관측한 fresh running이 하나라도 있으면 작업 중. 다른 승인 대기·지연은
   숨기지 않고 별도 개수/표식으로 같이 표시한다.
2. running이 없고 fresh waiting_approval이 있으면 승인 대기.
3. 위 둘이 없고 fresh blocked가 있으면 막힘.
4. 그 외 열린 세션 중 stale/unknown/조회 불완전이 있으면 일부 미확인.
5. 세션 조회가 해당 범위에서 완전하고 열린 세션이 하나 이상이며 모두 fresh
   idle이면 대기/idle. 모든 세션이 기준을 넘었을 때만 사용자 idle 배지를 표시.
6. 관측된 세션이 없으면 관측 없음, 알려진 세션이 모두 ended이면 관측 세션 종료.
   이전 세션 보존 만료를 로그인하지 않음/퇴근으로 표현하지 않는다.

사용자 idle 기간은 모든 열린 세션이 함께 idle이었던 시간이다.
따라서 가장 최근 idle_since_at을 사용한다(각 세션 idle_seconds의 최솟값).
idle 30분 세션과 idle 2분 세션이 있으면 사용자는 대기 2분이지 idle 30분이 아니다.
목록 일부 페이지로 idle을 확정하지 않는다. 집계 전용 서버 쿼리에 예산을 두고,
완전하게 계산할 수 없으면 coverage=partial 및 집계 미확인으로 반환한다.
숨겨진 다른 작업의 개수·존재를 coverage 설명을 통해 누출하지 않는다.

예시 화면(합성 데이터):

```text
작업자 | 이 프로젝트·허용된 조회 범위 | 14:40:00 기준

사용자  요약          관측 세션   마지막 보고   저장 확인
지민    작업 중       실행 1      4초 전        14:38
서연    idle 8분      idle 2      3초 전        14:29
민수    승인 대기     승인 1      5초 전        14:35
수현    일부 미확인   대기 1/지연1 2분 전(지연) 14:20
도윤    관측 없음     없음        -             -

펼치기: 서연
  Claude / 세션 A / idle 12분 / 보고 3초 전 / lease 미보유
  Codex  / 세션 B / idle  8분 / 보고 4초 전 / lease 유효
```

idle 배지는 자동 인수 후보 추천이나 업무 배정 동의를 뜻하지 않는다.
관리자가 배정하려면 기존 대상 적격성·프로젝트 권한·확인 절차를 그대로 거친다.

## 6. TUI 상호작용과 관리자 설정

- 작업자 탭은 사용자별 접힘/세션별 펼침, 내 세션, 상태, CLI 필터를 제공한다.
  필터와 집계 범위가 바뀌면 표시 설명도 바꾸고 선택 행은 안정된 ID로 유지한다.
- 주의 필요 영역에는 저장 실패, 소유권 만료 위험, 승인 대기, 보고 지연을
  보여준다. 일반 idle은 중립 색상이며 장애·근태 평가처럼 붉게 표시하지 않는다.
- 자세히 보기에서 판정 사유, 관측 출처/범위, 서버 확인 시각, 적용 정책,
  소유권과 저장 상태를 각각 읽을 수 있다. 실제 원문은 자동으로 열지 않는다.
- 목록에서의 조회·정렬·알림 숨김은 인계 ack가 아니다. 알림 숨김은 로컬이며
  별도 명칭을 사용한다. 같은 조건의 알림을 매 heartbeat마다 반복하지 않는다.
- 시간 경과/필터 갱신 때문에 목록 순서가 바뀌어도 확인 폼의 대상을 바꾸지 않는다.
- 키보드 탐색, 80x24의 세션 상세 화면, 한글/ASCII 상태명과 고대비를 검증한다.

관리 > 관측 정책에 다음 폼을 제공한다(명시적 --manage 및 서버 관리자 권한 필요):

| 설정 | 기본 | 제안 범위 |
| --- | --- | --- |
| heartbeat_seconds | 15 | 10~60 |
| stale_after_seconds | 60 | 45~300, heartbeat_seconds의 3배 이상 |
| idle_after_seconds | 300 | 60~3600 |

memory_presence_policy_get/set의 별도 versioned 관측 정책 계약을 사용한다.
M8 continuity policy는 strict 전체 replacement이므로 새 필드를 조용히 끼워
넣거나 구형 클라이언트 요청으로 관측 설정이 사라지게 하지 않는다.
관리자 변경에는 권한·expected_version·idempotency key·이유·미리보기·감사를
요구한다. 서버가 현재 정책으로 계산하고 policy_version을 표시한다.
임계값 변경은 표시 정책 변경일 뿐 새 작업 활동이 아니며 idle 시작을 초기화하지 않는다.
Core의 보고 주기는 재연결/정책 재확인 시 반영하고, 갱신 중에는 서버가 관측한
보고 주기/적용 버전을 명시한다. 서로 다른 설정을 쓰는 구간을 숨기지 않는다.
관측 정책 설정만으로 사용자 기기의 보고 opt-in을 원격 활성화하지 않는다.

## 7. 필수 판정 시나리오

| 입력 | 기대 결과 |
| --- | --- |
| 30분 동안 무출력 테스트 실행, 유효한 보고 지속 | 작업 중, idle 아님 |
| idle 299초 / 300초, fresh | 대기 / idle |
| 같은 idle 상태의 heartbeat 10회 | idle 시작 유지, last_seen만 갱신 |
| TUI poll·checkpoint·lease 자동 갱신 | idle 시작 유지 |
| 승인 대기 20분 | 승인 대기, idle 아님 |
| fresh idle 1개 + fresh running 1개 | 사용자 작업 중 |
| fresh idle 30분 + fresh idle 2분 | 사용자 대기 2분 |
| fresh idle 12분 + fresh idle 8분 | 사용자 idle 8분 |
| fresh idle 1개 + stale/unknown 1개 | 일부 미확인, 사용자 idle 확정 안 함 |
| running 1개 + stale 1개 | 작업 중 + 지연 표시 둘 다 유지 |
| 마지막 보고 59초 / 60초 | fresh / stale |
| stale 후 다시 idle 보고 | 새 연속 idle 구간, 단절 시간 제외 |
| 늦은 sequence / 중복 sequence | 활동·신선도·idle 시간 연장 없음 |
| ended 이후 늦은 보고 / 프로세스 재시작 | 기존 세션 종료 유지 / 새 세션 |
| 같은 사용자의 서로 다른 프로젝트 | 섞지 않고 별도 집계 |
| 세션 조회 partial 또는 권한 범위 축소 | 전체 사용자 idle로 오표시하지 않음 |
| 토큰 폐기·접근 철회 | 조회 거부/화면 제거, 익명 모드 fallback 없음 |
| TUI 종료·재시작 | 실제 Core 상태 보고 수명에 영향 없음 |
| TUI만 실행하거나 아직 opt-in하지 않은 사용자 | 관측 없음, idle/오프라인 추측 안 함 |
| idle 임계값 5분 -> 10분 변경, idle 지속 8분 | 대기로 재계산, idle 시작/lease/배정 불변 |
| 표시 시계 역행/서버 연결 끊김 | 시간 미확인/마지막 확인값, 가짜 최신 상태 없음 |

검증은 먼저 순수 판정 함수의 고정 시계 테스트, PostgreSQL의 sequence/권한/
정상 종료/동시성 테스트, 그 다음 TUI headless 렌더링·필터·오프라인 테스트로
나눈다. 실제 CLI/계정 관측 smoke는 명시적 opt-in으로 별도 수행한다.
이 문서의 예시와 표는 실행 결과가 아니며 M9 구현 완료 증거로 사용하지 않는다.
