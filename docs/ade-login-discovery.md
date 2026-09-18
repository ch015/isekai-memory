# ADE 서버 주소 기반 로그인 설정

2026-09-18. ADE U54와 함께 사용하는 공개 설정 계약이다.

`GET /auth/config`는 인증 없이 `{schema_version: 1, providers: {...}}`를 반환한다.
활성 공급자만 포함하며 `Cache-Control: no-store`를 적용한다. 브라우저 Origin 요청은 거부한다.

- `github`: `organization_id`. 기존 `/auth/github/config` 및 코드 교환/갱신 계약을 그대로 사용한다.
- `entra`: `organization_id`, `tenant_id`, `client_id`, `scope`.
  `client_id`는 기존 설정의 허용 ADE desktop 앱 ID이며, `scope`는 `api://<audience>/<scope>`다.
- 비활성 공급자는 키를 생략한다. 모두 비활성이면 빈 providers 객체다.
- endpoint, 로그인 비밀, 토큰, 허용 사용자 목록, 계정 정보는 반환하지 않는다.
  ADE는 사용자가 등록한 서버 주소에 응답을 결박하고 허용된 필드만 저장한다.

서버에 기존 Entra/GitHub 설정을 완료하면 사용자는 서버 주소를 한 번 등록하고 공급자 버튼으로 로그인한다.
토큰/인증 없음 연결과 공개 설정을 제공하지 않는 구형 서버의 수동 설정도 ADE 고급 설정에서 유지한다.
`/auth/me`, `/mcp`, 기존 API의 인증과 프로젝트 권한은 바뀌지 않는다.
새 환경 변수, 사용자 ID 변경, DB migration이 없다. 배포 실패 시 이전 이미지로 복귀할 수 있다.

검증: `tests/test_login_config.py`, `tests/test_entra.py`, `tests/test_github.py` 총 60개 통과.
공개 필드 정확성, 비밀 제외, 비활성 공급자, 기존 인증 API 보호와 Origin 거부를 확인했다.
실제 Entra 조직 로그인 검증은 포함하지 않는다.
