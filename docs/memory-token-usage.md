# M9 TUI: 사용자·작업별 모델 토큰 사용량

상태: **사용량 ledger/API·정책·Core parser/reporter/outbox·TUI 연결 구현 및 합성 검증**. 2026-09-14.
[현재 v1 구현 계약](memory-usage-runtime.md)을 우선 참조한다. 아래는 원 설계와
이전 순수 수치 단계의 기록도 포함한다. Core worker는 현재 작업 미연결 run으로
보고하며, 외부 부모 CLI·미확인 버전·Claude/Kiro 계측은 지원 완료로 표시하지 않는다.
[협업 TUI 준비서](memory-collaboration-tui.md)에 사용량 화면과 수집 계약을 추가한다.
새 로그인·Nunchi 인증 연동은 보류하고 기존 프로젝트 토큰을 사용한다.
여기서 토큰 사용량은 모델의 입력·출력 토큰 수이며 인증용 비밀 토큰과 다르다.

사용자의 최종 범위 확인: 핵심은 **토큰 사용량 모니터링**이다.
비용·예산·결제는 개발하지 않는다. 선택 알림은 기본 꺼짐이며 추가 기능 개발은 동결했다.
실행별 출처와 누락 사유는 사용량 화면에서 d → Enter로 확인한다.

## 1. 목표와 현재 구현의 한계

사용자는 내 오늘/선택 기간/세션/작업 사용량을, 관리자는 권한이 있는 프로젝트의
사용자별·작업별·CLI별·모델별 사용량을 확인한다. 수치는 **관측 범위 내 집계**이며
사용자의 전체 계정 사용량, 구독 잔여 한도 또는 실제 청구서를 의미하지 않는다.

다음은 최초 설계 시점의 Core 코드 기록이다. 현재 DTO/reporter는 구현 계약을 따른다:

- `src/isekai/host/base.py`의 `LocalHostAdapter.start`는
  `context_usage={method: estimated, input_tokens: max(1, len(prompt_payload) // 4)}`를
  반환한다. 이는 Core가 전달한 초기 프롬프트 바이트 수 기반의 거친 추정이며,
  내부 재시도·추가 턴·캐시·출력·전체 CLI 대화의 실제 사용량이 아니다.
- `src/isekai/execution/contract.py`는 이 값을 result envelope의
  `context_usage.mode/used/capacity`에 담는다. 이 계약을 누적 소비량으로 재해석하거나
  기존 `exact/estimated/unavailable` 의미를 조용히 바꾸지 않는다.
- 현재 Codex adapter는 JSON 출력을 요청하고 별도 마지막 메시지 파일을 읽으며,
  Claude adapter는 JSON 결과에서 요약을 추출한다. Kiro adapter는 ACP bridge 결과를
  읽는다. **이 전송 경로가 있다는 사실만으로 usage 필드 지원을 보장하지 않는다.**
  공통 WorkerResult에는 정규화된 실제 사용량 보고 계약이 아직 없다.
- Memory의 기존 offline generation에 있는 문자 수와 비용 0 기록은 CLI 모델 토큰
  사용량이 아니다. 이를 이 화면의 토큰 수나 모든 작업의 비용 0으로 옮기지 않는다.

현재 schema 012/80 tools에는 별도 opt-in 정책·소유권/receipt 원장·기간 집계가
연결됐다. Core는 기존 context_usage와 별도 DTO로 검증된 Codex 형식의 종료 usage를
보고하며 owner-only outbox를 사용한다. TUI의 f/j로 필터/관리 정책을 연다.
과거 기록 수집과 실제 계정/프로젝트 활성화는 하지 않았으며 기존 초기 프롬프트
추정치를 실제 소비량으로 소급 변환하지 않는다.

### M9-2b 첫 구현: 수치 의미

- 입력/출력/합계와 캐시 읽기·쓰기/추론의 여섯 필드마다 reported, estimated,
  unavailable을 구분한다. 추정 방법 및 누락 사유는 제한된 값으로 검증한다.
- 필드별 최대 10^12의 비음수 정수만 수락한다. bool/float/NaN/초과값과
  입력·출력·합계 모순, 부모보다 큰 부분값을 거부한다.
- 정규화 계약에서 캐시 읽기/쓰기는 입력의 서로 겹치지 않는 부분이고,
  reasoning은 출력의 부분이다. 실제 host mapping 확인 없이 이 계약을 쓰지 않는다.
- 입력과 출력의 품질/방법이 같고 둘 다 알려진 경우에만 빠진 합계를 계산한다.
  입력만 있는 경우, 합계만 있는 경우, 실제 0, 미수집을 구분한다.
- 같은 epoch의 절대 카운터 감소·품질 저하·수치 소실을 거부한다. 같은 범위의
  추정치→보고치 전환은 대체이며 더하지 않는다. 순수 집계는 최대 10,000개의
  이미 권한·최신 revision·비중복 범위가 검증된 단위를 인자로 받는 내부 함수다.
- **29개 순수 테스트 통과**. 이 결과는 CLI 사용량 수집, DB receipt 멱등성,
  부모/자식 중복 제거, 시간대 귀속 또는 실제 계정 검증 완료를 뜻하지 않는다.
  그러한 신원·sequence·범위·보존 검사는 다음 ledger/reporter 단계의 책임이다.

## 2. 화면과 표시 규칙

`[요약]`에 내 사용량 요약, `[작업자]`에 같은 기간의 사용자별 사용량 열,
별도 `[사용량]`에 기간·사용자·작업·CLI·모델 필터와 상세를 제공한다.
작은 화면에서는 상태/사용량을 별도 상세 화면으로 나누며 가로 폭을 무한히 늘리지 않는다.
관리자는 프로젝트 합계와 사용자별 내역, 일반 사용자는 기본적으로 자신의 내역만 본다.
협업 bundle을 볼 수 있다는 이유로 다른 사용자의 사용량까지 자동 공개하지 않는다.

합성 예시(아직 실제 데이터 화면 아님):

```text
사용량 | 프로젝트 A | 오늘 00:00~현재 Asia/Seoul | 관측된 Core 작업 기준
CLI 보고 합계 126,000 tokens | 추정치 별도 | 수집 누락 있음 | 8초 전 수신

사용자   상태          입력 합계   출력    합계       품질
지민     작업 중       100,000     26,000  126,000    CLI 보고 / 진행 중
서연     idle 8분      ~18,000     —       —          초기 프롬프트 추정만
민수     승인 대기     —           —       —          수집 불가

지민 상세: 입력 100,000 중 캐시 읽기 60,000 / 캐시 쓰기 미제공
          출력 26,000 중 reasoning 미제공; 미제공은 0이 아님
[기간] [내 작업] [CLI/모델별] [수집 상태] [관리: 사용량 알림 정책]
```

- 입력·출력·합계를 기본값으로 하고 캐시 읽기/쓰기, reasoning은 실제로 보고되고
  의미가 검증된 경우에만 펼쳐 보인다. 합계에 이미 포함된 세부 값을 다시 더하지 않는다.
- `reported`는 CLI/provider가 보고한 수치다. Memory가 청구서와 독립 검증했다는
  뜻의 “확정 청구량” 대신 “CLI 보고”로 표시한다.
- `estimated`는 `~`와 추정 방법/범위를 표시하고 reported 합계와 별도 집계한다.
  기존 초기 프롬프트 추정은 별도 항목이지 전체 사용량의 상한이나 대체값이 아니다.
- 미제공/미지원/잘린 출력은 `—`와 사유. `0`은 실제로 보고된 0에만 사용한다.
  입력만 알려지면 입력 부분합만 표시하고 전체 합계는 미확인으로 둔다.
- 품질과 완전성은 별도다: reported 수치도 `partial`, `in_progress`, `final`일 수 있다.
  마지막 usage 수신 시각과 관측 가능한 범위를 항상 제공한다.
- **컨텍스트 점유율**, **기간 누적 토큰**, **계정 구독 한도**, **비용**을 분리한다.
  현재 `context_usage` 추정만으로 실시간 컨텍스트 점유율을 확정하지 않는다.
- 토큰 수가 늘지 않는다고 idle로 판정하지 않는다. 종료된 작업의 늦은 usage 보고도
  사용자 활동/heartbeat/lease를 갱신하지 않는다. [idle 계약](memory-presence-idle.md) 유지.

## 3. 수집 위치와 지원 수준

```text
Core가 관측한 CLI/worker의 구조화된 usage
 -> host별 parser: 의미·버전·범위 확인, 허용된 숫자 필드만 추출
 -> Core usage reporter: 인증된 사용자/작업 결박, 재전송·중복 방지
 -> Memory usage ledger/권한별 집계
 -> 사용자·관리자 TUI: 보고치/추정치/누락과 갱신 시각 표시
```

TUI가 모델을 호출해 사용량을 물어보거나 MCP 호출 횟수를 토큰으로 환산하지 않는다.
직접 조회/집계는 새 모델 생성을 요구하지 않는다. 하지만 CLI가 MCP 결과를 모델
컨텍스트에 넣어 발생한 사용량은 해당 CLI의 관측 대상이며, MCP 서버만으로는
외부 CLI의 전체 모델 사용량을 알 수 없다.

host parser의 단계:

1. 구현 시 설치된 CLI/adapter 버전과 공식 구조화 인터페이스를 확인하고 합성
   fixture로 필드 의미·누적/증분·캐시 포함 관계를 검증한다. 3종 모두 지원한다고
   미리 선언하지 않는다. 모르는 스키마는 추측하지 않고 unsupported로 반환한다.
2. 현재 실행 완료 후 결과를 읽는 경로부터 시작한다. 이 경우 갱신 주기는 **작업
   종료 후**이며 5초 TUI poll이나 presence heartbeat가 실시간 계측을 만들지 않는다.
3. 지원이 검증된 host에 한해 턴/스트림 이벤트를 추가한다. 그때만 “진행 중 갱신”을
   표시한다. 이벤트가 없는 긴 실행은 “usage 결과 대기”이지 소비량 0이 아니다.
4. Core 바깥의 대화/부모 CLI는 별도 opt-in 관측 adapter가 없으면 미수집이다.
   로컬 전체 대화 이력·다른 프로젝트 로그를 자동 탐색하거나 화면을 스크래핑하지 않는다.

현재 Codex 0.154.0의 단일 fresh thread/turn JSONL mapping은 공식 문서와 합성 fixture로 검증했다.
다른 버전과 Claude/Kiro는 현재 unsupported다. 실제 계정의 소비량과 청구값 비교는 수행하지 않았다.
실 CLI smoke는 사용자 계정과 명시적 실행 허용을 갖춘 별도 검증으로 기록한다.
인증정보/원문을 볼 필요 없이 숫자·출처·수집 상태만으로 TUI fixture를 먼저 검증한다.

## 4. 정규화 계약 초안

usage는 presence heartbeat와 별도 계약이다. 현재 runtime envelope 스키마에
필드를 몰래 추가하지 않고 선택적 WorkerUsage DTO와 runtime protocol을 버전 관리한다.

| 묶음 | 후보 필드 / 규칙 |
| --- | --- |
| 신원·소유 | project_id, 서버 인증 actor_id, server_session_id, execution_attempt_id, 선택적 work/unit 연결 |
| 출처 | host_kind/version, adapter_version, provider, model_id(모르면 unknown), source_kind, observation_scope |
| 중복 식별 | meter_epoch, source_unit_id, source_sequence, payload_digest, 선택적 parent 관계 |
| 수치 | input_total_tokens, output_total_tokens, total_tokens; cache_read/write_input_tokens, reasoning_output_tokens |
| 수치 의미 | field 단위 reported/estimated/unavailable, semantics_version, estimate_method, omission_reason |
| 범위·완료 | granularity=request/turn/run, coverage, completion_state, source_interval, usage_revision |
| 시간 | source_occurred_at, source_time_quality, server_received_at, aggregate_as_of, bucket_basis |

인증 토큰에서 actor를 결정하고 session/attempt/work의 프로젝트·소유 관계를
서버에서 확인한다. reported actor 문자열이나 임의 work ID로 타인에게 사용량을
전가할 수 없다. 인계/재배정 전의 사용량은 실제 보고한 이전 actor에 남는다.
명시적인 연결이 없으면 “작업 미연결”로 보존하고 현재 활성 작업에 임의 배분하지 않는다.

정규화 시 다음 불변식을 검증한다:

- 기본 합계는 `input_total_tokens + output_total_tokens`. 정규화된 입력 합계에는
  검증된 캐시 입력을 한 번만 포함하고 reasoning은 출력의 부분집합으로 취급한다.
  provider 원본이 캐시를 입력과 분리하는 경우에는 서로 배타적이라는 mapping을
  검증한 후 한 번 합친다. 포함 관계를 모르면 세부값을 unknown으로 남긴다.
- provider가 합계만 제공하면 합계는 reported로 남길 수 있지만 입력/출력을
  역으로 만들어내지 않는다. 모순되는 세부값은 오류/부분 보고로 표시한다.
- 비음수 정수만 수락하며 bool, float, NaN, 음수, 필드/합계 상한 초과를 거부한다.
  null은 0이 아니다. 입력/출력/합계 관계와 실제 선언된 부분집합 제약을 검사한다.
- provider/model을 모르면 unknown 그룹을 유지한다. 화면상의 기본 모델명이나
  토큰 수로 모델을 추측하지 않는다. 서로 다른 tokenizer의 합계는 운영 참고치이지
  모델 간 동일 작업량·효율 또는 청구 단위의 보장이 아니다.

## 5. 중복·재시도·기간 집계

정규화된 각 관측 단위는 **절대 카운터의 versioned 보고**로 보낸다. 누적값을
수신할 때마다 새 소비량처럼 더하지 않는다. 예를 들어 같은 단위의 100 -> 150은
최신값 150이며 250이 아니다. ledger 원본 receipt와 유효 revision을 분리한다.

- 프로젝트/인증 actor/attempt/meter/source unit에 유일 키를 둔다. 같은 sequence와
  digest 재전송은 같은 receipt; 동일 키의 다른 payload는 충돌; 오래된 revision은
  최신값을 되돌리지 않는다. 저장과 집계 반영은 원자적으로 처리한다.
- counter reset은 명시적인 새 epoch로 시작한다. 같은 epoch에서 수치 감소는
  거부한다. 정정이 필요한 provider는 별도 검증된 revision/supersede 계약을 사용하며
  조용히 음수 delta를 적용하지 않는다. 정정 이력은 남긴다.
- 네트워크 재전송과 실제 모델 재호출은 다르다. 재전송은 1회, 실제 재시도/실패/
  취소된 호출의 보고된 소비량은 서로 다른 attempt/source unit으로 각각 집계한다.
- 한 attempt의 같은 범위를 request/turn/run 수준으로 중복 집계하지 않는다.
  parser가 검증한 하나의 집계 수준만 선택한다. 부모 합계와 자식 합계를 동시에
  더하지 않고, 부모 자신의 별도 모델 호출만 독립 단위로 센다.
- 추정치와 실제 보고가 같은 범위를 가리키면 보고치로 대체하고 합산하지 않는다.
  범위가 다른 초기 프롬프트 추정은 별도 참고값으로 남긴다. 세분화 수준 변경이나
  중복 observer 사이의 대응 관계를 확인할 수 없으면 ambiguous/partial로 표시하고
  확정 합계에 둘 다 넣지 않는다. 자동 로그 import/backfill은 이번 범위가 아니다.
- TUI가 아닌 Core reporter가 bounded owner-only outbox로 receipt까지 재시도한다.
  숫자·최소 식별자만 저장하고 인증정보/대화 본문을 제외한다. 401/403에는 전송을
  중단하며 다른 actor/project로 재전송하지 않는다. 큐 용량/보존 초과는 수집 gap으로
  드러내고 조용히 성공 처리하지 않는다. 실행 실패나 원문 삭제가 소비량 0을 뜻하지 않는다.
- presence와 달리 usage는 과거 소비 보고를 늦게 보낼 수 있다. 종료된 세션의
  소유 관계가 검증되고 권한이 유효하면 정해진 지연 허용 기간 내 수락하되 presence를
  되살리지 않는다. 늦은 보고와 정정은 과거 합계 revision을 갱신하고 화면에 표시한다.

기간 선택은 오늘/이번 주/사용자 지정이며 표시 timezone을 명시한다. “오늘”은
선택한 timezone의 00:00부터 현재까지의 반열린 UTC 구간으로 서버에서 계산한다.
일광 절약 시간과 경계값을 포함해 날짜만으로 임의 24시간을 더하지 않는다.

관측 단위의 유효 발생 시각이 있으면 해당 시각을 사용하고, 없거나 검증 범위를
벗어나면 서버 최초 수신 시각을 사용해 수신 기준임을 표시한다. 재전송 수신 시각으로
날짜를 옮기지 않는다. run 합계밖에 없으면 종료일 귀속이며 시간 비례로 나누지 않는다.
진행 중 run은 임시 귀속/진행 중으로 표시하고 최종 종료일 확정 시 이전 기여분을
원자적으로 교체한다. 자정 전후를 정확한 시간대별 소비로 가장하지 않는다.

합계는 권한 범위 전체를 처리하는 bounded 집계 쿼리로 제공한다. 현재 목록 페이지를
더한 값을 프로젝트 총량으로 쓰지 않는다. 응답은 기간, timezone, metric semantics,
quality별 소계, 관측 가능한 누락/미지원 상태, observed_at/revision, coverage를 포함한다.
관측 밖 작업을 분모로 알 수 없으므로 “전체 계정의 100% 수집”이라고 표시하지 않는다.

## 6. API·보안·관리자 설정

다음 도구/모듈은 schema 012의 현재 80개 목록에 연결됐다. v1 report는 단일
exclusive run revision이며 register/prune도 추가됐다. 자세한 제한은 구현 계약을 따른다:

- `memory_usage_report`: 인증된 reporter의 bounded batch, idempotent receipt.
- `memory_usage_summary/list`: 권한별 기간 집계와 유한 상세, scoped cursor.
- `memory_usage_policy_get/set`: 별도 versioned 수집 보존/알림 정책.
- Memory `continuity/usage.py` 및 저장 계층, Core `host/` parser와 `memory/usage.py`,
  기존 runtime protocol/kernel 연결, `cli/console/` presenter를 분리한다.
  execution -> memory 직접 import, TUI -> SQL 직접 연결을 도입하지 않는다.

사용량 조회는 기존 bundle 가시성과 별개의 최소 권한이다. 기본은 자신의 해당
프로젝트 내 사용량, 프로젝트 admin만 그 프로젝트 전체를 조회한다. 별도 read-all
권한은 후속 명시적 계약 없이는 부여하지 않는다. 숫자·카운트·모델명·누락 사유도
같은 필터를 적용하고 숨겨진 사용자/프로젝트 존재를 누출하지 않는다.
report 권한도 기존 서버 scope 관례와 통합하되 사용자 임의 admin 보고는 금지한다.
조회 응답은 no-store이며 권한 철회/프로필 전환 시 TUI 캐시를 비운다.

원문 대화·프롬프트·출력·파일 경로·계정 인증 키·provider 계정 식별자는 전송하지 않는다.
usage 식별자는 필요한 범위로 namespace/불투명화하고 원시 구조화 이벤트 전체를
Memory에 저장하지 않는다. 분류 등급은 연결 작업 이상으로 유지하며 필터링한다.
telemetry opt-in과 보존/정리 정책은 presence와 별도로 정하고 사용자의 기기를
관리자 설정만으로 원격 감시 시작하지 않는다. 수집된 값은 신고된 운영 지표이지
조작 불가능한 정산 증거 또는 근태 평가 근거가 아니다.

관리 > 사용량 정책(제안): 프로젝트/사용자별 기간 토큰 **알림 기준**, 조회 timezone,
보존 기간/상한, 수집 허용 설정. 알림 기본은 꺼짐이며 관리자 저장은 권한 검사,
expected_version, 이유, 미리보기, idempotency, 감사를 요구한다. M8 strict 전체
replacement 정책이나 presence 정책에 조용히 새 필드를 끼워 넣지 않는다.

알림은 reported 합계를 기준으로 하며 추정치/미지원 때문에 실제 사용량이 더 클 수
있음을 표시한다. 같은 사용자/기간/정책 버전/임계치 알림은 중복 억제한다. 값 정정이나
기간 전환 시 상태를 다시 평가한다. **알림만 제공**하며 자동 작업 중지·모델 변경·
강제 인수·계정 제한은 하지 않는다. 확정 예산 차단은 실행 전 예약/병렬 호출/정산 계약이
필요한 별도 범위다. 실제 요금·환율·구독 잔여 한도 조회도 이번 범위에 포함하지 않는다.

## 7. 구현 순서와 수용 테스트

M9-2b로 usage DTO·의미 정규화·ledger·권한별 집계를 추가하고 M9-3 사용량 화면,
M9-4 관리자 알림 폼으로 연결한다. presence 전체 구현이 끝나야만 순수 usage parser
테스트를 시작할 필요는 없지만, 원격 보고에는 인증된 세션/attempt 결박이 필요하다.
새 로그인이나 세 CLI의 모든 usage 기능을 기다리느라 공통 TUI를 막지 않는다.
미지원은 명시하고, 검증된 지원부터 점진적으로 제공한다.

| 시나리오 | 기대 결과 |
| --- | --- |
| reported 입력 100/출력 20, 입력 중 캐시 읽기 60, 출력 중 reasoning 5 | 합계 120; 185로 중복 합산하지 않음 |
| 입력/캐시 배타 제공 또는 포함 관계 미상 | 검증된 mapping만 정규화; 미상은 명시 |
| 입력만 보고 / 실제 0 / usage 미제공 | 전체 합계 미확인 / 0 / — 구분 |
| 현재 Core 프롬프트 추정치 | 초기 입력 추정만 표시; 실제 소비/컨텍스트 점유율로 둔갑하지 않음 |
| 누적 100 -> 150, 같은 보고 3회 재전송 | 최종 150, receipt 하나씩 수렴 |
| 오래된 보고 / 같은 키의 다른 payload / counter reset | 최신값 유지 / 충돌 / 새 epoch 요구 |
| 실제 재시도 2회, 실패·취소에도 유효 usage 있음 | 서로 다른 소비는 각각 집계 |
| 부모 합계와 자식 합계 / 중복 observer / 추정치 대체 | 단일 집계 범위; 불명확하면 부분/중복 가능 표시 |
| 한 사용자 여러 CLI·장치 / 모델 변경 / 작업 인계 | 범위 내 합계, 모델별 분리, 기존 actor 귀속 유지 |
| final-only host가 20분 작업 / 스트리밍 가능 host | 결과 대기 / 관측 이벤트에 맞춰 갱신; poll로 가짜 계측 없음 |
| outbox 재시도·TUI 종료 / 권한 철회 | durable 중복 방지 / 전송 차단, 익명·다른 계정 fallback 없음 |
| ended 세션의 늦은 보고 / idle 중 과거 usage 도착 | 허용 범위에서 과거 합계 수정; 활동·lease 불변 |
| 자정·timezone·DST·늦은 보고·진행 중 run 확정 | 명시된 귀속 기준과 revision; 날짜 간 이중 합산 없음 |
| 목록 여러 페이지 / 필터·권한 축소 / 일부 미지원 | 서버 scoped 합계, 누출 없음, partial 명시 |
| 음수·bool·초대형 정수·불일치 합계·미지 schema | bounded 거부/미지원; 원문 오류·비밀 로그 없음 |
| 알림 기준 초과·동시 갱신·정정·정책 충돌 | 알림 중복 억제/감사; 자동 중단·배정·가격 계산 없음 |
| 원문 삭제·세션 정리·사용량 보존 만료 | 개인정보 정책에 따른 정리, dangling 소유 관계/가짜 0 없는 조회 |

순수 parser/집계 fixture -> PostgreSQL 동시성·receipt·권한·보존 테스트 -> headless
TUI 테스트 -> 명시적으로 허용된 real CLI smoke 순서로 검증한다. 이 표는 실행 결과가
아니며 synthetic fixture 통과를 실제 계정/청구량 검증으로 표현하지 않는다.
