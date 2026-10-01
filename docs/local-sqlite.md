# SQLite 로컬 DB 모드

Memory를 별도 PostgreSQL/Docker 없이 로컬 파일 하나에 저장한다. Python 3.11 이상과
Python에 연결된 SQLite 3.38 이상이 필요하다. 기존 PostgreSQL 모드는 계속 지원하며 기본값도 유지한다.

## 설치와 실행

```bash
pip install -e .
isekai-memory --sqlite ~/.local/share/isekai-memory/memory.db --mode http
```

첫 실행에 디렉터리·DB·schema 020·이벤트 커서 키를 자동 생성한다. 같은 파일로 다시 실행하면
기존 데이터를 사용한다. SQLite에는 `alembic upgrade head`가 필요하지 않다.
기존 PostgreSQL 데이터는 자동으로 이동하지 않는다. 새 SQLite 파일은 독립된 저장소다.

기본 주소는 `http://127.0.0.1:8100/mcp`다. `--port`와 `--host`로 바꿀 수 있다.
SQLite를 선택했어도 설정 파일/환경/CLI에 명시한 host는 우선한다.
HTTP 인증은 그대로 켜져 있으므로 ADE용 토큰을 같은 DB에 발급한다.

```bash
isekai-memory --sqlite ~/.local/share/isekai-memory/memory.db \
  --issue-token --project-id directory --user-id alice --scopes admin,projects
```

출력의 `token`을 ADE의 Memory 연결 인증정보에 저장하고, 위 MCP 주소로 연결한다.
`admin,projects`는 개인 서버 관리자의 예시다. 다른 사용자에게는 별도 계정의
`read,write,projects` 토큰을 발급하고 기존 프로젝트 구성원 설정으로 공유 범위를 정한다.
원래 사용 중인 ADE·Foundation·Presets는 DB 종류를 알 필요가 없으며 기존 HTTP API로 연결한다.

MCP 프로세스를 직접 실행하는 클라이언트는 다음 명령을 사용한다.
stdio의 인증 경계는 기존과 같이 해당 프로세스를 실행하는 OS 사용자다.

```bash
isekai-memory --sqlite ~/.local/share/isekai-memory/memory.db --mode stdio
```

## 환경 변수와 JSON 설정

CLI `--sqlite FILE`이 설정 파일·환경 변수의 DB 주소보다 우선한다.
같은 경로를 재사용하려면 절대 경로를 권장한다.

```bash
export ISEKAI_MEMORY_DATABASE_URL='sqlite:////absolute/path/memory.db'
isekai-memory --mode http
```

```json
{
  "database_url": "sqlite:////absolute/path/memory.db",
  "server": {"mode": "http", "port": 8100}
}
```

`sqlite:///memory.db`는 실행 디렉터리 기준 상대 경로다. 파일 경로에 `#`나 `?`가 있다면
`--sqlite FILE`을 사용하거나 URL에서 인코딩한다. `:memory:` 임시 DB와 SQLite URI 옵션은 지원하지 않는다.
PostgreSQL의 `db.pool_min/max`는 SQLite에서 사용하지 않는다.

## 기능과 동시 접근

기존 89개 MCP 도구를 동일한 인증·프로젝트 범위·수신자·버전 규칙으로 제공한다.
Git/일반 디렉터리 프로젝트, 자료·작업 이력, Task/Result 인계, 체크포인트, 결정사항 검색,
경험·Skill·팀 자산, 상태·사용량·이벤트를 같은 DB에 보관한다.

SQLite는 프로세스마다 비동기 작업용 연결 하나를 사용한다. 쓰기 트랜잭션은
`BEGIN IMMEDIATE`로 같은 파일을 여는 다른 프로세스와도 순서대로 처리한다.
만료 시간은 잠금을 얻은 후 다시 확인하며, 실패·취소 시 롤백한다.
WAL, 외래 키, 이력 변경 방지 트리거와 읽기 전용 트랜잭션을 활성화한다.
새 파일은 사용자 전용 권한으로 만들며, 다른 용도의 DB나 알 수 없는 스키마는 초기화하지 않는다.

검색은 로컬 단어 일치·부분 문자열 방식이며 한글 검색과 기존 인용 형식을 유지한다.
PostgreSQL의 검색 설정 이름(`postgres_lexical`, `postgres_weighted_lexical`)은 호환 입력으로 받고,
응답 `strategy`는 실제 구현인 `sqlite_lexical` 또는 `sqlite_weighted_lexical`을 표시한다.
두 DB의 관련도 점수와 동점 순서는 동일하다고 보장하지 않는다. 임베딩·벡터 DB는 추가하지 않는다.

여러 PC가 작업을 공유할 때는 한 PC에서 실행하는 Memory HTTP 서버에 연결한다.
각 PC의 독립 SQLite 파일끼리 자동 복제하지 않는다. DB 파일은 서버의 로컬 디스크에 두고,
네트워크 공유 폴더나 클라우드 동기화 폴더를 DB 연결 경로로 사용하지 않는다.
동시 쓰기가 많은 중앙 서버에는 기존 PostgreSQL 모드를 사용한다.

## 상태 확인과 백업

`GET /ready`는 DB와 테이블·뷰·트리거, schema revision을 검사하고 `backend: "sqlite"`를 반환한다.
`GET /health`와 나머지 MCP/REST 경로는 기존과 같다.

실행 중에는 `memory.db-wal`, `memory.db-shm` 보조 파일이 생길 수 있다.
백업하려면 해당 DB를 사용하는 HTTP/stdio 프로세스를 모두 정상 종료한 후 DB 파일을 복사한다.
실행 중 백업이 필요하면 SQLite의 online backup API를 사용한다. 실행 중 `.db` 파일만 복사하면
WAL의 최신 변경이 빠질 수 있다. 복원도 모든 연결을 종료한 상태에서 한다.

## 개발 검증

```bash
pip install -e '.[test]'
pytest --sqlite -q
```

`--sqlite`는 임시 DB를 자동 생성하고 종료 시 정리한다. 기존 DB 통합 테스트를 재사용하며,
PostgreSQL 내부 잠금/카탈로그 전용 3개 및 Alembic 업그레이드 전용 2개 테스트만 제외한다. SQLite 전용 테스트는 파일 재사용,
다중 프로세스 쓰기, 동시 초기화, 읽기 전용 처리, 취소·롤백, SQL 시간 제한, CLI 토큰 관리,
실제 HTTP/stdio 프로세스와 재시작 후 이력 보존을 확인한다.

SQLite 기본 스키마는 `store/sqlite_schema/020_*.sql`에 패키지 리소스로 포함한다.
향후 PostgreSQL 스키마를 변경할 때 SQLite 변경·업그레이드 경로도 함께 작성해야 한다.
SQL 차이는 `store/sqlite_dialect.py`의 AST 변환에서 처리하고 사용자 값은 항상 바인딩한다.
알 수 없는 구문을 문자열 치환으로 숨기거나, 잠금을 생략해 동작시키지 않는다.
SQLite는 `aiosqlite`와 `sqlglot` 두 Python 라이브러리를 추가로 사용하며 DB 서버 프로세스는 없다.

2026-10-01의 전체 테스트·ADE 검증 결과는 [검증 기록](sqlite-validation.md)에 정리했다.
