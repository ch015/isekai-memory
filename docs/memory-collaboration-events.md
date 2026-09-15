# M9 변경 알림과 재접속

2026-09-14. schema 013 / Memory 82 tools. [M9 검증표](memory-m9-acceptance.md).

## 사용과 의미

`isekai watch`의 알림 탭은 현재 권한으로 볼 수 있는 최근 변경 메타데이터를 최대 100건 표시한다.
n으로 밀린 변경을 더 읽고 z로 커서를 폐기한 뒤 전체 조회한다. 조회는 ack/claim/renew가 아니다.
기본 대화형 TUI는 XDG_STATE_HOME/isekai/console/events 아래 owner-only 파일에
불투명 cursor와 연결 binding hash만 보관한다. 본문·bearer·알림 내용은 저장하지 않는다.
`--no-event-resume`은 메모리 내 커서만 사용하고 `--once`도 파일을 만들지 않는다.
다른 actor/프로젝트/endpoint/credential reference의 커서를 섞지 않는다.

MCP 도구:

- memory_collaboration_events: mine 또는 관리자 project 범위, 분류 상한, cursor, limit 1–50.
- memory_collaboration_events_prune: 관리자·이유·idempotency key, 한 번에 최대 200건.
  기존 불변 감사 이력을 지우지 않는다.

## 담는 변경 / 담지 않는 내용

저장본 생성, 인계/재배정, 수신 확인, claim/반납/완료, 접근 철회, 정책 변경,
세션 등록/상태 변경/종료, 첫 사용량 final, 유지보수 신호를 투영한다.
일반 heartbeat·lease 주기 갱신·토큰 하나마다 이벤트를 쌓지 않는다.
final usage 정정은 현재 사용량 조회에서 반영한다. 모든 경험/legacy MCP 변경을 포괄하는
전체 감사 스트림은 아니다. TUI는 이벤트가 없어도 현재 화면을 정기 조회한다.

DTO는 임의 상세/본문/actor/수신자 목록/숨겨진 sequence를 노출하지 않는다.
현재 resource 권한·분류·보존 상태를 SQL limit 전에 검사한다. 철회된 기존 수신자에게는
새 배정 내용 대신 target_id 없는 access_changed만 보내고 화면의 오래된 상세를 제거한다.
presence 분류 상승도 이전 분류 범위에 내용 없는 재조회 신호를 보낸다.

## 트랜잭션과 복구

원본 변경과 feed를 같은 트랜잭션에 기록한다. 프로젝트 head 행 잠금을 commit까지 유지하여
먼저 번호를 예약한 미완료 트랜잭션을 건너뛰는 cursor 유실을 막는다. rollback은 feed도 되돌린다.
보존은 7일/프로젝트 최대 50,000건, 쓰기/명시적 prune 시 최대 200건씩 정리한다.
만료된 행이 아직 정리되지 않았어도 보존 공백을 감지한다.

cursor는 DB에 보관한 32-byte 키와 고수준 Fernet으로 암호화·인증한다.
고정 길이 payload로 내부 위치와 scope hash를 감추지만 Fernet의 발급 시각은 공개된다.
직접 만든 암호 알고리즘이 아니라 [공식 Fernet 계약](https://cryptography.io/en/stable/fernet/)을 사용한다.
actor/프로젝트/현재 권한/scope/분류를 결박하며 cursor는 인증 수단이 아니다.

첫 접속, 만료, 손상, DB 복원/키 변경, 보존 공백은 새 watermark와 reset_required를 반환하고
그 watermark 뒤에 전체 상태를 조회한다. 잘못된 타인/scope 커서는 거부한다.
권한 변경으로 기존 커서가 거부되면 TUI가 중단·화면 제거 후 r 재확인 시 이전 커서를 무시한다.

화면이 요청 generation에 맞는 조회 결과를 실제 수락했을 때만 커서를 진행·저장한다.
실패한 화면 조회, 늦은 응답, 닫힌 화면은 커서를 소비하지 않는다. 저장 실패는 조회를
막지 않고 로컬 재개 불가로 표시한다. 서버 읽음 확인이나 다른 장치의 수신 확인은 아니다.

## 운영

의존성 설치 뒤 운영자 승인하에 `python -m alembic upgrade head`를 수행해야 한다.
013은 기존 012 기록을 보존하고 초기 과거 이벤트를 임의 생성하지 않는다.
이벤트가 한 번이라도 발행된 DB의 013 downgrade는 정리 후라도 거부한다.
알림 이력이 없는 경우만 012 rollback이 가능하다. 키를 로그/문서/소스에 복사하지 않는다.
운영 적용·키 회전·실제 구독 CLI 실행은 이번 작업에서 수행하지 않았다.

검증: DB 권한/분류/동시 commit/rollback/보존/키 변경, TUI 수락 시점/커서 분리,
실제 HTTP 서버 프로세스 재시작 후 새 Core TUI의 cursor 재개, 손상 cursor 전체 갱신,
별도 DB의 populated 012 보존·empty rollback·history-aware downgrade refusal.
