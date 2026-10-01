# SQLite 모드 검증 — 2026-10-01

수정 저장소는 `isekai-memory`다. ADE/Presets/Foundation은 기존 HTTP 계약을 사용하므로 수정하지 않았다.
SQLite는 새로운 저장 방식이며 PostgreSQL의 schema 020 및 89개 도구 계약을 유지한다.
기존 PostgreSQL 데이터를 SQLite로 이관하거나 운영 서버 설정을 교체하지 않았다.

| 검증 | 결과 |
| --- | --- |
| `pytest --sqlite -q` 전체 테스트 | 760 passed, 5 skipped |
| 임시 PostgreSQL 14.20에서 `MEMORY_TEST_DATABASE_URL=... pytest -q` | 765 passed |
| 최종 SQLite DB 통합·전용 회귀 | 210 passed, 3 skipped |
| SQLite 최종 전용 회귀 `pytest -q tests/test_sqlite.py tests/test_sqlite_transports.py` | 9 passed |
| 동일 파일 동시 최초 실행 | 독립 연결 4개 × 12회 통과 |
| Wheel 빌드 및 패키지에서 DB 생성·readiness | SQL 리소스 6개 포함, 실행 통과 |
| 변경 Python 파일 Ruff / `git diff --check` | 통과 |
| ADE `tests/manual/memory-sharing.py`, SQLite HTTP | Git 및 directory 각각 통과 |

제외한 5개는 PostgreSQL 내부 row/advisory lock·카탈로그 검사 3개와 Alembic 업그레이드 2개다.
SQLite의 독립 연결·다중 프로세스 쓰기 직렬화, 읽기 전용 처리, savepoint/취소 롤백은 별도 테스트했다.
전체 실행 중 Python 3.14와 기존 pytest-asyncio의 이벤트 루프 정책 관련 deprecation 경고가 발생했다.

ADE 검증은 두 개의 독립 설치, 서로 다른 인증·Lock, 자료·작업 이력, HTTP 인계의 로컬 컨텍스트 주입,
경험 검색 인용, 체크포인트 준비, 수신자의 기존 파일 보존, 제거한 구성원의 접근 거부를 확인했다.
SQLite 파일과 HTTP 프로세스를 임시 디렉터리에 만들었으며 실제 사용자의 프로젝트·인증·DB는 사용하지 않았다.
이번 변경에서 화면 코드는 수정하지 않았고 Electron GUI 재검증은 하지 않았다.

## 저장 계층 검수

- SQL 값은 계속 파라미터로 바인딩한다. AST 변환은 UUID·JSON 배열·시간·검색·잠금 구문의 DB 차이만 처리한다.
- UUID 대소문자, UTC 시간 정규화와 마이크로초, JSON 내용 비교, NULL의 SQL 의미를 유지한다.
- SQLite 쓰기 잠금 획득 후 만료 시각을 다시 확인한다. claim generation 및 수신 영수증 조건은 기존 로직을 쓴다.
- 외래 키·CHECK·고유 제약·이력 보호·원본 삭제 시 Skill 무효화 트리거를 유지한다.
- 동시 초기화 시 WAL 전환의 잠금 경쟁을 제한 시간 내 재시도하고, 실패하면 시작을 중단한다.
- SQLite에는 별도 관리자/권한 정책이나 추가 백그라운드 서비스가 없다.
- 검색 결과의 권한·분류 필터와 출처 검증은 공통 로직을 사용한다. SQLite의 관련도 점수는 PostgreSQL과 다를 수 있다.

실행 방법과 저장·백업 범위는 [로컬 SQLite 운영 안내](local-sqlite.md)를 따른다.
