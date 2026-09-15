# M9 완료 검증표

완료 기록: 2026-09-15. 구현·최종 테스트: 2026-09-14. **로컬 구현·합성 검증 완료**.
운영 배포·프로젝트 활성화·실제 구독 CLI 실행·새 인증·커밋·푸시 완료를 의미하지 않는다.

기준 저장소 HEAD: Memory `99a3d91`, Core `a7caff2`. 기존 M8/사용자 미커밋 변경을 보존했다.
Core의 기존 staged `.isekai/state.db`에는 추가 unstaged 변경이 없다.
원격 최신성 재확인이나 Git push는 이번 완료 작업에서 수행하지 않았다.

## 완료 범위

| 단계 | 구현 / 검증 근거 |
| --- | --- |
| M9-0/1 | 사용자·관리자 공통 화면, 기존 credential_ref/서버 actor, 권한·분류·페이지·카운트 조회. `test_memory_overview.py`, `test_console_model.py`, `test_collaboration_overview_postgres.py`, `core_overview_e2e_smoke.py` |
| M9-2/2a | opt-in worker/controller 세션, idle/승인/실행/지연 분리, 사용자별 관측 범위 집계. `test_controller_presence.py`, `test_memory_presence.py`, `test_presence_state.py`, `test_presence_postgres.py`, `core_presence_e2e_smoke.py` |
| M9-2b | 토큰 보고/추정/누락, 버전·출처, 절대 revision/재시도, 권한·기간 집계. `test_host_usage.py`, `test_usage_reporter.py`, `test_usage_read.py`, `test_usage_runs.py`, `test_usage_metrics.py`, `test_usage_postgres.py`, `core_usage_e2e_smoke.py` |
| M9-3 | Textual 선택 의존성, profile/--once, 80x24/120x36, 한글·긴 값·키보드·주입 방지, 단일 요청·오래된 응답 배제·철회 시 화면 제거. `test_console_app.py`, `test_console_model.py`, `test_console_pending.py`, `core_console_e2e_smoke.py` |
| M9-4 | 모든 M8 정책/기본·예비·인계자별 1:N, 복구 발행, 분담/긴급 재배정, 감사, 본문 삭제, 관측 정책, 경험 검색·검토. `test_admin_*` 및 `test_experience_*`, `core_admin_policy_e2e_smoke.py`, `core_admin_actions_e2e_smoke.py`, `core_experience_e2e_smoke.py` |
| M9-5 | 사용자 저장/인계/확인/claim/격리 준비/완료/반납, 작업 세션 격리, 독립 lease 갱신기. `test_work_session.py`, `test_workbench.py`, `test_work_forms.py`, `test_lease_keeper.py`, `test_work_selection_postgres.py`, `core_work_e2e_smoke.py` |
| M9-6 | 트랜잭션 순서 보장 feed, 별도 불투명 cursor, 권한 필터·보존 공백 전체 갱신, 서버 재시작 재개, migration/패키지. `test_events*.py`, `test_event_read.py`, `test_event_forms.py`, `core_events_e2e_smoke.py`, `migration_events_e2e_smoke.py` |

이 표의 파일명은 해당 책임을 가진 Memory 또는 Core 저장소 기준이다.
[원래 수용 체크리스트](memory-collaboration-tui.md#수용-테스트)는 이 **지원 범위와 합성 검증** 기준으로 완료 처리한다.
세 CLI의 모든 기능 지원, 사람의 재실/근태 감시, 운영 부하 인증을 뜻하지 않는다.

## 최종 실행 결과

| 확인 | 결과 |
| --- | --- |
| Memory 전체 PostgreSQL 테스트 | **650 passed** (schema 013) |
| Core 전체 테스트 | **819 passed, 5 skipped**, 273.62초 |
| 최종 Core wheel / Python 3.11.16 | **372 passed**, 실제 설치 패키지로 console/admin/controller/presence/usage/work/lease/events/experience 검증 |
| 기본 Core wheel | Textual/Rich 없이 console 명령·독립 작업 세션 모듈 import 통과 |
| Memory wheel | 빌드 후 임시 위치에 설치, main/events/usage import 통과 |
| HTTP/stdio 전체 합성 E2E | **82 tools / schema 013**, 관리자·수신자 TUI, 모든 기존 M0–M8 흐름과 M9 연동 통과 |
| 실제 서버 프로세스 재시작 | 새 Core TUI가 저장 cursor로 변경 재개; 손상 cursor는 전체 조회, 관찰 중 작업 변경 없음 |
| 별도 migration DB | populated 012 보존, 이벤트 없는 013→012 rollback, 재업그레이드 키 보존, 이벤트 이력 있는 downgrade 거부 |
| Ruff / whitespace | 양 저장소 전체 Ruff 및 `git diff --check` 통과 |

372개 설치본 테스트와 개별 focused suite는 전체 테스트와 겹친다. 합쳐서 새로운 고유 테스트 수로 보고하지 않는다.
Memory 경고 2,206개는 테스트 실패가 아니지만 경고가 전혀 없었다고 주장하지 않는다.
Core skip은 실제 구독 실행 opt-in 4개와 샌드박스 프로세스 조회 제한 1개다.
프로세스 트리 검증의 이전 별도 승인 실행 통과는 전체 suite의 no-skip 실행과 구분한다.

### 재현 진입점

- Memory: `MEMORY_TEST_DATABASE_URL=<격리 DB> PYTHONPATH=src python -m pytest`.
- Core: `PYTHONPATH=src python -m pytest`. 실제 구독 opt-in 환경변수는 설정하지 않는다.
- 전송/TUI: Memory의 `tests/run_local_e2e.py`; `MEMORY_CORE_SOURCE`, `MEMORY_CORE_PYTHON`,
  `MEMORY_CORE_CONSOLE_TESTS=1`과 별도 합성 DB를 지정한다.
- Migration: **새 빈 별도 DB**로 `PYTHONPATH=.:src python tests/migration_events_e2e_smoke.py`.
  기존 데이터가 있는 DB를 비우거나 재사용하지 않는다.

실제 검증은 loopback PostgreSQL/HTTP와 임시 프로젝트·사용자 토큰을 사용했다.
HTTP 자식 프로세스는 종료하고 합성 토큰은 회수했다. 기존 전용 테스트 Docker/DB는 재검증을 위해 남겼다.
운영 DB나 실제 프로젝트에서 인수·인계·삭제·활성화를 수행하지 않았다.

## 사용 시작

Core에서 선택 의존성을 설치한 뒤 기존 Memory 연결이 있는 프로젝트에서:

```sh
python -m pip install -e '.[console]'
isekai watch                     # 기본 관찰
isekai watch --work              # 내 작업; 별도 continuity opt-in 필요
isekai watch --manage            # 기존 서버 관리자 권한 필요
isekai watch --work --manage     # 같은 TUI에서 두 모드
```

- 내 인수함/작업 → w → 확인/claim/격리 준비 → 기존 Core 실행·승인 → 완료/반납.
- g: 기존 로컬 작업 저장본 생성. 내 저장본 → w: 정책의 인수자들에게 인계. y: 미확정 작업 재확인.
- c: M8 정책, o: 관측 정책, u/b/x/h: 복구 발행/재배정/본문 삭제/감사.
- 사용량은 화면에서 확인. f: 필터, d: 개별 실행, Enter: 출처·누락 사유.
- k/v: 기억 검색/관리자 검토. 알림 탭 n: catch-up, z: 전체 재동기화.
- 사용자 신원은 Git 정보가 아닌 기존 Memory 토큰의 actor다.

[Core 사용자 작업 계약](memory-user-work-console.md), [알림 운영 계약](memory-collaboration-events.md),
[관측 한계](memory-controller-runtime.md)를 먼저 확인한다.
서버 운영 적용은 별도 승인과 백업 뒤 의존성 설치·schema 013 migration이 필요하다.

## 토큰 범위와 명시적 제외

사용자 요청에 따라 **토큰 사용량 모니터링을 핵심으로 확정하고 추가 확장을 중단**했다.
개발 중 추가된 선택 알림은 기본 꺼짐으로 유지한다. 비용 계산·환율·예산·결제·구독 잔여 한도,
자동 작업 중단·모델 변경은 만들지 않았다.

Codex 0.154.0의 단일 fresh thread/turn 구조화 결과 mapping은 공식 문서와 합성 fixture로 검증했다.
CLI 버전 확인만 수행했으며 실제 계정의 모델 실행/청구 대조는 하지 않았다.
공식 usage 포함 관계를 적용해 캐시/추론을 총량에 다시 더하지 않는다.
[공식 출력 형식](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable),
[공식 usage 의미](https://developers.openai.com/api/docs/guides/agents-api/observability#understand-token-usage).
OpenAI 문서 skill은 이 mapping 검증에 사용했고 지원 범위를 명시적으로 제한하는 데 반영했다.

Claude/Kiro와 미확인 Codex 버전은 현재 unsupported다. Core 밖의 부모 CLI 대화도 미수집이다.
수집은 종료 후 갱신이며 TUI의 5초 poll은 실시간 토큰 스트리밍이 아니다.
현재 Core usage는 Memory 작업 UUID와 임의 결합하지 않는 unlinked run이다.
미수집은 null/사유이지 0이 아니고, 작업자 idle은 사람의 부재 판정이 아니다.
새 로그인/Nunchi/Jira/Wiki connector, 조직 회원 관리, 자동 이탈/배정, 운영 활성화·배포·커밋·푸시는 별도 범위다.
