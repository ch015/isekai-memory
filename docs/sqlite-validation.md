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

## Docker 기본 SQLite 실행 검증 — 2026-10-01

Docker 이미지의 기본 DB를 `/data/memory.db`로 설정하고 `appuser` 쓰기 권한과 `/data` 볼륨을 추가했다.
환경 변수로 기본값을 제공하므로 토큰 발급도 같은 DB를 사용하고, 기존 Compose의 PostgreSQL URL은 우선한다.
위 전체 pytest 결과는 SQLite 저장 계층 도입 당시 기록이며, 이번 Docker 변경에서는 아래 실행 검증을 수행했다.

| 검증 | 결과 |
| --- | --- |
| `scripts/build-image.sh`로 실제 ARM64 이미지 빌드 | 통과 |
| 기본 CMD로 HTTP 시작, 호스트 공개 포트의 `/ready` | `backend: sqlite`, 스키마 자동 생성 확인 |
| 실행 사용자·DB 권한 | non-root, 소유자 일치, DB 파일 0600 |
| DB 옵션 없이 `docker exec ... --issue-token` | 동일 SQLite DB 발급 및 HTTP 인증 통과 |
| 일반 디렉터리 프로젝트·한글 작업 이력 저장/검색 | 통과 |
| 컨테이너 삭제 후 동일 named volume으로 새 컨테이너 생성 | 기존 토큰·프로젝트·작업 이력 유지 |
| 토큰 회수 및 미인증 접근 | 회수 후 401, 미인증 401 |
| PostgreSQL 환경 변수 명시 | 컨테이너 내 설정이 PostgreSQL URL을 선택 |
| 기존 Compose 설정 해석 | PostgreSQL URL·마이그레이션·HTTP 명령 유지; 스택 재기동은 하지 않음 |

이 Mac의 ARM Docker VM에서는 기존 OpenSSL CPU 감지 문제로 기본 실행이 종료 코드 132로 중단됐다.
`cryptography 50.0.2` 단독 import에서도 재현했고, `OPENSSL_armcap=0`을 전달해 위 실행 검증을 통과했다.
우회 설정은 해당 환경의 실행 옵션이며 이미지의 전역 기본값으로 추가하지 않았다.
임시 컨테이너·볼륨만 사용하고 검증 후 제거했다. 사용자의 기존 서버와 DB는 변경하지 않았다.
