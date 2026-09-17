# GitHub OAuth 로그인 (schema 016)

GitHub.com 전용 OAuth 앱의 code+PKCE 교환, 앱 귀속 토큰 확인, 숫자 사용자 ID 허용 목록을 구현한다.
Entra OIDC 및 기존 Memory token과 병행 가능하다. GitHub 로그인은 OIDC ID token을 사용하는 흐름이 아니다.
실제 OAuth 앱 등록값을 아직 제공받지 않았으며, 운영 배포·실제 GitHub 동의·Windows 인수는 별도다.

## 설정

ADE 전용 OAuth App을 만들고 callback URL을 `http://127.0.0.1/github/callback`으로 등록한다.
GitHub loopback 예외에 따라 ADE는 임의 포트를 요청한다. wildcard callback과 device flow는 사용하지 않는다.
server 환경변수 또는 JSON `auth.github`로 설정한다. secret은 서버 비밀 저장소로 공급한다.

| `ISEKAI_MEMORY_GITHUB__` 뒤의 이름 | 값 |
| --- | --- |
| ENABLED | 기본 false |
| CLIENT_ID | 전용 GitHub OAuth App client ID |
| CLIENT_SECRET | 서버 전용 앱 secret; ADE에 배포하지 않음 |
| ALLOWED_USER_IDS | JSON 문자열 배열, 예: `["123456"]`; 운영자가 확인한 불변 숫자 ID |
| ALLOW_LEGACY_TOKENS | 기본 true; false면 기존 수동 token을 차단 |

DevSecOps 고정이며 enabled일 때 빈 secret·빈 허용 목록·숫자가 아닌 ID·auth_enabled=false를 거부한다.
활성 Entra/GitHub 중 하나라도 legacy=false이면 수동 token은 거부하되 두 활성 공급자는 함께 허용한다.
이메일·GitHub login 이름·organization 이름으로 사용자를 자동 승인하지 않는다.

## 서버 API와 경계

| API | 인증 | 의미 |
| --- | --- | --- |
| GET `/auth/github/config` | 공개 | client_id, 고정 scope, DevSecOps만 반환 |
| POST `/auth/github/exchange` | OAuth code + PKCE verifier | code/code_verifier/redirect_uri → 토큰·검증된 identity |
| POST `/auth/github/refresh` | OAuth refresh token | refresh_token → 회전한 토큰·동일 공급자 identity |
| GET `/auth/me` | Memory bearer | user_id/provider/organization_id |

공개 교환은 JSON 4 KiB 제한, Origin 헤더 거부, CORS 미제공, no-store다.
허용 redirect는 `http://127.0.0.1:<1..65535>/github/callback`뿐이다. state 검증은 ADE 일회용 loopback에서 수행한다.
GitHub HTTPS의 고정 code endpoint에 server secret과 PKCE verifier를 함께 제출한다. redirect는 따라가지 않는다.
응답도 64 KiB로 제한한다. worker마다 원격 GitHub 요청은 분당 120회·동시 8개로 제한한다.
공유 배포의 프록시에는 별도의 클라이언트별 rate limit을 둔다. 프록시/APM에 Authorization과 교환 본문을 기록하지 않는다.

GitHub 토큰은 `Bearer iskgh.<GitHub access token>`으로 구분한다. 단순 `/user` 조회가 아니라
`POST /applications/<configured client ID>/token`으로 **이 OAuth 앱에 발급된 토큰**인지 확인한다.
`read:user offline_access`만 요청하며 광범위한 scope(repo/user 등)가 포함된 기존 grant도 거부한다.
PAT, 다른 OAuth 앱 토큰, 봇, 허용 목록 외 사용자, 로컬 차단 사용자는 거부한다.
GitHub 검증 결과는 토큰의 SHA-256을 key로 최대 60초·1024개 캐시한다. 비밀 토큰은 DB에 저장하지 않는다.
매 요청 허용 목록과 로컬 disable/조직을 다시 확인하고, 도구의 프로젝트 권한은 기존 경로에서 확인한다.
GitHub에서의 토큰 권한 회수는 이 캐시 기간 내 지연될 수 있다.

## DB·사용자 연결

schema 016은 `memory_github_identities`와 협업 eligibility view의 GitHub owner/write member를 추가한다.
숫자 ID별 기본 user_id는 `github:<ID>`다. 프로젝트 전역 admin은 주지 않으며 프로젝트 owner만 해당 프로젝트 admin이다.
Entra와 이름·이메일이 같아도 자동 합치지 않는다. 기존 기록 연결은 첫 로그인 전에 운영자가 명시적으로 수행한다.

```bash
isekai-memory --bind-github-user <숫자-ID> --user-id <기존-Memory-user_id>
isekai-memory --disable-github-user <숫자-ID>
isekai-memory --enable-github-user <숫자-ID>
```

이 명령은 서버의 DB 접근 권한이 있는 로컬 운영자용이다. MCP/REST 관리 API로 노출하지 않는다.
기존 binding 변경·중복 user_id binding을 거부한다. disable은 다음 인증 요청과 협업 eligibility에서 즉시 적용된다.
GitHub와 Entra의 두 identity를 같은 Memory user에 명시적으로 연결했다면 긴급 차단 시 두 identity와 기존 token을 각각 차단한다.

배포는 DB 백업 → 요청 중지 → 새 서버 준비 → `alembic upgrade head` → 서버 시작 → `/ready` revision **016** 확인 순서다.
GitHub를 비활성으로 사용하더라도 새 코드의 schema는 016이어야 한다. downgrade는 GitHub identity binding을 삭제하므로 데이터 백업 없이 실행하지 않는다.
이 개발 작업은 운영/로컬 사용 중인 서버 DB를 수정하지 않았다.

## 모듈과 테스트

- `server/github_config.py`: 설정·불변 subject 검증.
- `server/github.py`: 고정 GitHub endpoint, 교환·갱신, 앱 검증·캐시·허용 목록.
- `server/github_routes.py`: 작은 공개 HTTP 교환 경계.
- `store/github_identities.py`, `server/github_admin.py`: 로컬 사용자·차단·명시적 연결.
- `tests/test_github.py`: 잘못된 앱/subject/scope/redirect, refresh, route/body limit, 설정 검증.
- `tests/test_github_postgres.py`: 실제 임시 PostgreSQL에서 Entra/GitHub 프로젝트 할당·차단·협업 대상 검증.

전체 Memory 회귀 719개가 임시 PostgreSQL에서 통과했다. 실제 GitHub/조직 OAuth 정책은 fixture 테스트에 포함하지 않는다.

공식 근거: [OAuth/PKCE/갱신/loopback](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps),
[OAuth 앱 토큰 확인](https://docs.github.com/en/rest/apps/oauth-applications),
[네이티브 앱 비밀 관리](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/best-practices-for-creating-an-oauth-app).
