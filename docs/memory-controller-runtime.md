# M9 Core 컨트롤러 관측

상태: 로컬 구현·합성 단위/HTTP 검증, 2026-09-14.
[관측 API](memory-presence-runtime.md)와 [idle 의미](memory-presence-idle.md)를 유지한다.
최종 전체 결과는 [M9 완료 검증표](memory-m9-acceptance.md)를 따른다. 실제 구독 CLI 계정 실행 검증은 아니다.

- opt-in 프로젝트의 장기 MCP Gateway가 initialize를 받으면 컨트롤러 관측을 시작한다.
  중복 initialize는 세션을 늘리지 않는다. EOF/입출력 오류/Kernel 종료 시 종료 보고,
  프로젝트 초기화로 Kernel을 교체할 때는 기존 관측을 끝내고 새 관측을 만든다.
- 직접 수행하는 Core 작업만 active 집합으로 센다. 중첩 작업이 모두 끝나야 idle이다.
  조회·TUI poll·자동 lease 갱신은 활동 전환이 아니다. CLI 외부 작업과 사람의 입력은 관측하지 않는다.
- 직접 받은 WAITING_GATE 응답은 승인 대기로 표시한다. 알려진 기한이 지나거나
  기한을 검증할 수 없으면 blocked, 명시적 승인/거절 응답을 받으면 그 대기를 제거한다.
  다른 프로세스에서 바뀐 승인 상태를 실시간 감시하는 기능은 아니다.
  등록되지 않은 과거 SQLite RUNNING 기록을 현재 실행으로 간주하지 않는다.
- worker에는 서버가 확인한 같은 actor/project 부모만 연결한다. 부모 등록이 아직
  확인되지 않았거나 인증이 바뀌면 연결을 만들지 않는다. 부모의 비밀 capability는 공유하지 않는다.
- 관측 메타데이터는 internal 이상이며 명시적 상위 context 분류를 따라 올리고 내리지 않는다.
  로컬 작업 식별자, 명령, 원문, 경로는 업로드하지 않는다. 세션 수는 작업 수가 아니다.
- 매 tick와 종료는 동일 credential snapshot으로 신원 조회 후 쓰기 한다.
  다른 actor로 토큰이 교체되면 등록/heartbeat/end 전에 중단한다. 기존 세션은 종료 미확정/
  stale이 될 수 있으며 새 사용자 세션으로 둔갑시키지 않는다.
- 최신 상태만 전송한다. 상태 변경은 coalesce하고 초당 최대 한 번 보고하며,
  평상시 주기는 서버 정책(기본 15초), 네트워크 실패 backoff 상한은 60초다.
  offline heartbeat queue는 없다. pending gate/blocked 집합은 각각 128개 제한;
  초과 시 unknown이지 idle이 아니다.
- 배경 스레드는 SQLite/Kernel에 접근하지 않는다. 최신 진단은
  .isekai/presence/controller-latest.json에 0600으로 남기며 비밀/원문은 포함하지 않는다.
  TUI를 켜고 닫는 것은 관측·worker·lease의 수명과 무관하다.

검증: 새 controller 단위 17개, 관련 presence/host usage 포함 69개 통과.
기존 Gateway·관측·사용량·패키지 경계 62개 통과. 실제 localhost Memory HTTP에서
idle→running(부모/worker)→idle→승인 대기→승인 후 idle, 다른 actor로 토큰 교체 시
쓰기 차단과 정상 종료를 확인했다. M0–M9 HTTP/stdio 전체 합성 smoke도 통과했다.
Codex/Claude/Kiro 구독 계정은 실행하지 않았다.
