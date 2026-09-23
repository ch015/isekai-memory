# 로컬 Docker 빌드·실행

AWS/ECS/RDS/ECR 배포 설정이 아닌 **개인 개발 PC용 Memory 서버 + PostgreSQL** 구성이다.
Core/TUI는 기존처럼 호스트에서 실행하고 이 Memory HTTP 주소로 연결한다.
Docker Engine/Desktop과 Compose v2가 필요하다. 로컬 Python 설치는 필요 없다.

## 한 번에 실행

isekai-memory 저장소 루트에서:

```sh
docker compose up -d
```

`docker compose up`만 실행해도 빌드·DB·마이그레이션·서버·포트 연결이 함께 처리되며,
포그라운드 로그가 표시된다. 준비까지 기다리고 결과를 확인하려면 아래 스크립트를 쓴다.

```sh
./scripts/local.sh up
```

```text
로컬 이미지 빌드
 → PostgreSQL 16 준비 확인
 → migrate: alembic upgrade head (성공 후 종료)
 → Memory 서버 시작
 → /ready로 DB 연결·스키마 확인
```

마이그레이션이 실패하면 서버를 시작하지 않는다. migrate가 Exited (0)인 것은 정상이다.
준비 순서는 Compose의 [health/completion 의존 조건](https://docs.docker.com/compose/how-tos/startup-order/)을 사용한다.
이미 떠 있는 서버를 새 스키마로 갱신할 때는 먼저 down한 뒤 up한다.
실행 중 요청과 마이그레이션의 무중단 호환성은 이 로컬 구성에서 보장하지 않는다.

- MCP: `http://127.0.0.1:8100/mcp`
- 준비 확인: `http://127.0.0.1:8100/ready`
- API 문서: `http://127.0.0.1:8100/docs`
- DB: Compose 내부 `db:5432`에만 제공. 호스트 DB 포트는 열지 않는다.

기본 호스트 바인딩은 127.0.0.1이며 같은 PC에서만 접근한다.
팀 접속은 HTTPS 프록시 또는 암호화된 터널로 제공한다. 다른 인터페이스에 바인딩하려면
`ISEKAI_LOCAL_BIND_HOST`를 명시하고 접근 범위를 제한한다. 원격 평문 HTTP는 토큰을 암호화하지 않는다.
기존 토큰 인증은 그대로 필요하며 DB 포트는 호스트에 공개하지 않는다.
서버 컨테이너 내부의 0.0.0.0은 Docker 포트 연결을 위한 값이다.
Docker socket이나 소스·사용자 홈 디렉터리를 컨테이너에 마운트하지 않는다.

## 빌드·운영 명령

```sh
./scripts/local.sh build
./scripts/local.sh up
./scripts/local.sh status
./scripts/local.sh check
./scripts/local.sh logs memory
./scripts/local.sh logs db
./scripts/local.sh logs migrate
./scripts/local.sh down
```

스크립트는 어느 작업 폴더에서 호출해도 자신의 저장소 compose.yaml/.env를 사용한다.
예: `/absolute/path/isekai-memory/scripts/local.sh status`.
up은 최대 120초간 준비 상태를 기다리고, 실패하면 0이 아닌 종료 코드를 반환한다.
처음 이미지 다운로드/빌드에는 별도의 시간이 걸릴 수 있다.

down은 이 스택의 컨테이너와 네트워크만 제거한다.
DB는 프로젝트별 named volume에 남으므로 다음 up에서 기존 데이터가 유지된다.
이미지/볼륨 전체 정리나 DB 초기화 명령은 스크립트에 넣지 않았다.
`docker compose down --volumes`를 직접 실행하면 DB가 삭제되므로 주의한다.
Docker 재시작 후 DB/서버는 unless-stopped 정책을 따르지만,
명시적으로 내린 컨테이너는 다음 up으로 시작해야 한다.

## 선택 설정

.env가 없어도 기본값으로 실행된다. 필요할 때만 .env.example을 .env로 복사하고 편집한다.
비밀번호가 들어 있다면 .env를 0600으로 보관한다. .env는 Git과 Docker build context에서 제외된다.

```dotenv
COMPOSE_PROJECT_NAME=isekai-memory-local
ISEKAI_LOCAL_BIND_HOST=127.0.0.1
ISEKAI_LOCAL_PORT=8100
ISEKAI_LOCAL_DB_PASSWORD='isekai-local-only'
```

기본 DB 사용자/DB 이름은 `isekai / isekai_memory`다.
기본 DB 비밀번호는 공개된 **로컬 개발용 값**이며 운영 비밀이 아니다.
개인 PC의 Docker 관리자도 신뢰 경계 안에 있으므로 Docker inspect/config는 비밀번호를 볼 수 있다.
실제 비밀번호로 바꿔도 운영 secret 관리나 TLS를 대신하지 않는다.

비밀번호는 DSN 문자열에 넣지 않고 PGPASSWORD로 전달하므로 @/:/$ 등 URL 특수문자를
직접 URL 인코딩할 필요가 없다. .env에서 $를 문자 그대로 쓰려면 작은따옴표로 감싼다.
환경 변수 기반 비밀 전달은 로컬 편의용이며 운영 환경은 별도 secret 관리가 필요하다.
관련 동작과 주의사항은 [PostgreSQL 환경 변수 문서](https://www.postgresql.org/docs/16/libpq-envars.html)를 따른다.

**DB 볼륨 생성 후 .env의 비밀번호만 바꿔도 기존 DB 비밀번호는 바뀌지 않는다.**
기존 값으로 되돌리거나 별도로 DB 비밀번호를 변경해야 한다. 자동 데이터 삭제로 해결하지 않는다.
프로젝트 이름을 바꾸면 다른 컨테이너·볼륨·로컬 이미지 이름을 사용한다.
포트 충돌 시 ISEKAI_LOCAL_PORT를 바꾼다. 여러 스택은 프로젝트 이름과 호스트 포트를 모두 구분한다.
ISEKAI_MEMORY_DATABASE_URL 같은 호스트 환경 값으로 운영 DB가 우연히 연결되지 않도록
이 Compose의 DB 접속 대상은 내부 db로 고정했다.

## 프로젝트별 사용자 키와 TUI

기존 토큰 인증은 켜져 있다. 로그인/Nunchi/RBAC을 추가하거나 인증을 우회하지 않는다.
up은 기본 관리자나 토큰을 자동 생성하지 않는다. 필요할 때 직접 발급한다.

```sh
# 프로젝트별 일반 사용자
./scripts/local.sh token project-a developer-a

# 해당 프로젝트 관리자
./scripts/local.sh token project-a admin-a admin

# 발급된 token_id로 명시적인 회수
./scripts/local.sh revoke <token-id>
```

발급 명령의 JSON에는 원문 token이 **한 번 출력**된다.
서버 로그·Git·프로젝트 JSON에 복사하지 말고 기존 host-local credential 파일
또는 ISEKAI_MEMORY_CREDENTIAL_* 환경 변수에 보관한다. 재실행하면 새 키가 발급된다.
이 키는 GitHub push 토큰이 아니며 다른 프로젝트 권한을 자동으로 얻지 않는다.
018부터 등록된 프로젝트는 토큰 사용자도 소유자의 명시적인 멤버 할당이 필요하다.
[여러 사용자 운영·갱신 절차](multiuser-operation.md)를 따른다.

호스트에서 `isekai watch` → a로 프로젝트를 등록한다.

- endpoint: `http://127.0.0.1:8100/mcp` (포트를 변경했다면 해당 값).
  다른 PC의 Core/TUI에서는 팀용 HTTPS 주소 또는 로컬 터널 주소를 입력한다.
- project_id: 발급 때 지정한 project-a.
- credential_ref: 토큰을 저장한 기존 credential 이름.
- expected_actor_id: 발급 때 지정한 사용자 ID (선택).
- organization_id: 기존 Core 연결의 조직 식별자 (로컬 예: local).
  조직 ID만 입력한다고 서버 권한이 생기는 것은 아니다.

DB는 빈 상태에서 시작한다. 인수 정책·관측·토큰 수집은 기존 관리 절차로 설정한다.
Core worker나 Codex/Claude/Kiro CLI를 컨테이너가 자동 실행하지 않으며,
추가 생성 worker/모델 호출도 기본 비활성이다.

## 문제 확인

```sh
./scripts/local.sh status
./scripts/local.sh logs migrate
./scripts/local.sh logs memory
docker compose exec db psql -U isekai -d isekai_memory -c 'SELECT version_num FROM alembic_version'
```

Docker daemon 오류는 Docker Desktop/Engine 상태를 확인한다.
마이그레이션 오류는 로그를 고치고 다시 up한다. 실패한 DB를 자동 초기화하지 않는다.
서버가 healthy인데 인증 실패면 발급 프로젝트·사용자·credential_ref를 확인한다.
순수 재시작은 소스 변경을 반영하지 않는다. 변경 적용은 build/up으로 한다.

### Apple Silicon에서 시작 직후 종료 코드 132가 발생할 때

ARM Docker VM에서 `cryptography.hazmat.bindings._rust`를 불러올 때
`Illegal instruction`이 발생한다면 OpenSSL의 CPU 기능 감지 경로를 확인한다.
2026-09-17 로컬 환경에서는 `cryptography 50.0.1`로 이 오류를 재현했고,
`OPENSSL_armcap=0`을 전달하면 모듈 로딩과 RSA/JWT·AES-GCM 검증이 통과했다.
해당 환경에서만 `.env`에 다음을 추가한 뒤 `./scripts/local.sh up`으로 다시 생성한다.

```dotenv
OPENSSL_armcap=0
```

이 설정은 OpenSSL의 ARM CPU 가속 감지를 건너뛰므로 성능에 영향을 줄 수 있다.
암호화 라이브러리 버전과 인증 설정은 그대로 유지한다.
Compose는 이 선택 변수를 Memory 컨테이너에 전달하며, 설정하지 않으면 컨테이너에서 제거한다.
VM 업데이트 후 문제가 해결되면 `.env`에서 해당 줄을 제거하고 다시 up한다.
근거: [OpenSSL ARM CPU 감지 구현](https://github.com/openssl/openssl/blob/openssl-4.0.2/crypto/armcap.c),
[Compose environment의 값 없는 변수 처리](https://docs.docker.com/reference/compose-file/services/#environment).
