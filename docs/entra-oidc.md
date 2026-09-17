# Entra OIDC API 인증 (schema 015)

Memory는 ADE public client가 얻은 **Memory API용 v2 delegated access token**을 검증한다.
단일 workforce tenant이며 client secret이 필요하지 않다. OIDC는 기본 비활성, 기존 opaque token 인증은 기본 유지다.
배포되지 않은 코드 변경이다. 실제 tenant/MFA/조건부 접근 인수는 남아 있다.

## 설정

`ISEKAI_MEMORY_ENTRA__ENABLED=true`와 아래 환경변수를 서버에 전달한다. Compose는 `.env.example`의 동일한 키를 전달한다.

| 변수 suffix (`ISEKAI_MEMORY_ENTRA__`) | 값 |
| --- | --- |
| TENANT_ID | 회사 tenant GUID |
| AUDIENCE | Memory API 앱 GUID (scope URL이 아님) |
| CLIENT_ID | 허용할 ADE desktop 앱 GUID |
| SCOPE | Memory.Access |
| REQUIRED_ROLE | ADE.User |
| ORGANIZATION_ID | DevSecOps (로컬 Compose 고정) |
| ALLOW_LEGACY_TOKENS | true: 기존 token 병행, false: Entra만 허용 |

JSON config에서는 `auth.entra` 또는 `entra` 객체로 동일한 소문자 필드를 전달한다.
`auth_enabled=false`와 Entra enabled 조합은 설정 오류로 거부한다.

Entra API app에 delegated scope `api://<API GUID>/Memory.Access`, Users/Groups 앱 역할 `ADE.User`,
`api.requestedAccessTokenVersion=2`를 설정한다. DevSecOps 사용자/그룹에 역할을 할당하고 Enterprise app의 사용자 할당을 필수로 한다.
Desktop app은 같은 tenant의 public client, `http://localhost` loopback redirect,
Memory delegated permission 및 조직 정책에 따른 admin consent가 필요하다.
[scope 설정](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-expose-web-apis) ·
[앱 역할과 토큰](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps) ·
[API token version](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens).

## API·identity·권한

`server/entra.py`는 고정 Microsoft tenant JWKS(1시간 cache, 30초 재조회 제한), RS256 서명,
issuer/audience/tid/azp/ver/exp/nbf/iat/scp/roles를 확인한다. Graph/ID token은 허용하지 않는다.
GET `/auth/me`는 bearer 인증 후 `user_id`, `provider`, `organization_id`만 no-store로 돌려준다.
reverse proxy는 HTTPS로 `/mcp`, `/auth/me`를 같은 origin에 노출한다.

`store/identities.py`는 `(tid,oid)`→내부 user_id를 결박한다. 첫 로그인 시 `entra:<tid>:<oid>`가 생성된다.
이메일·표시 이름으로 기존 사용자를 합치지 않는다. `projects/service.py`가 기존 소유권/멤버십과 조직을 검사한다.
Entra 로그인은 global admin 권한을 만들지 않고 project owner에만 해당 프로젝트 admin을 허용한다.
schema 015의 `memory_eligible_members`는 live legacy token 사용자와 활성 Entra owner/write member를 합쳐
인계·협업 대상 조회가 token 발급 없이도 동작하게 한다.

## 기존 소유권 연결·즉시 차단

**첫 OIDC 로그인 전에**, DB 접근 권한이 있는 운영자가 다음 명령으로 기존 user_id를 연결한다.
이미 identity 또는 user_id가 결박돼 있으면 실패한다. 기존 기록을 이동하거나 자동 합치지 않는다.

```sh
isekai-memory --bind-entra-user <object-guid> --tenant-id <tenant-guid> --user-id <existing-user-id>
isekai-memory --disable-entra-user <object-guid> --tenant-id <tenant-guid>
isekai-memory --enable-entra-user <object-guid> --tenant-id <tenant-guid>
```

Entra role 회수는 이미 발급된 토큰에 즉시 반영되지 않을 수 있다. 긴급 차단은 로컬 disable과 기존 token revoke를 함께 사용한다.
프로젝트 할당 해제는 다음 프로젝트 요청에서 바로 검사한다. 운영자 명령은 MCP에 노출하지 않는다.

## 배포·검증

기존 DB 백업 → 요청 중지 → 새 의존성/이미지 준비 → `alembic upgrade head` → 새 서버 시작 → `/ready`의 revision 015 확인.
015는 identity table/view를 추가한다. downgrade는 새 OIDC identity mapping을 삭제하므로 백업·운영 판단 없이 실행하지 않는다.
이 개발 작업은 실제 사용자의 로컬 서버/DB에 마이그레이션을 적용하지 않았다.

테스트는 `test_entra.py`의 로컬 RSA 서명 fixture, `test_entra_postgres.py`의 별도 PostgreSQL이다.
전체 서버 회귀는 임시 DB에서 688개 통과했고, oid 타입 오류 보완 후 Entra 검증 30개가 통과했다.
실제 Entra tenant, MFA, 조건부 접근, HTTPS 배포는 별도 인수다.
