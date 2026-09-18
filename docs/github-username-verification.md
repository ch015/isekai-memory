# GitHub 사용자명 허용 목록 — 구현·검증

2026-09-18. 사용자 요청: 기존 `ISEKAI_MEMORY_GITHUB__ALLOWED_USER_IDS`에 사용자명을 직접 입력.

## 책임과 계약

- `server/github_config.py`: 기존 숫자 ID와 사용자명을 정규화하고 대소문자 무관 비교.
  숫자 문자열은 기존 ID로 유지하며 `@123`은 숫자로만 된 사용자명이다.
- `server/github.py`: 앱 귀속 토큰에서 확인한 subject/login을 허용 목록과 비교한 후 기존 resolver 호출.
- `store/github_identities.py`와 DB schema는 변경하지 않는다. 내부 user_id, 사용자 binding,
  프로젝트·기록·멤버 권한과 로컬 disable 의미는 그대로 유지된다.
- 별도 사용자명 조회 API/설정 파일/DB 이관은 없다. 기존 allowlist와 secret을 자동 변경하지 않는다.

## 실패와 복구

잘못된 배열/항목은 기존처럼 시작 시 검증 오류다. 비허용 사용자/다른 앱 토큰/로컬 차단은 인증 실패다.
GitHub 조회 실패를 무인증이나 이전 사용자로 대체하지 않는다. `.env`를 고친 후 Compose를 재생성한다.
사용자명 변경/재사용은 이름 기반 허용 계약이며 [운영 설명](github-login.md)에 기록했다.
allowlist 수정은 캐시된 identity에도 적용하며, 공급자의 이름/권한 변화 반영은 기존 최대 60초 캐시를 따른다.

## 검증

- GitHub/공개 로그인 설정 테스트 52개 통과 후, HTTP route의 숫자 ID·사용자명 두 경로도 통과했다.
- 환경변수의 사용자명·숫자 혼용/중복/대소문자, 기존 `github:42` 유지, 숫자 사용자명과 ID 충돌 방지,
  토큰 앱 검사, 허용 목록 제거, 이름 변경, 로컬 disable, 비밀 비노출을 검증한다.
- 변경 Python 파일 Ruff, `git diff --check`, `docker compose config --quiet` 통과.
- 외부 GitHub 동의 화면·운영 서버·실제 PostgreSQL을 사용한 인수는 이번 검증에 포함하지 않는다.
  `.env`, 실행 중 컨테이너와 사용자 DB는 수정하지 않았다.

ADE의 원격 HTTP 허용은 ADE 저장소 U70에서 별도로 구현한다. Memory 서버의 HTTP listener와
OAuth 앱으로 향하는 HTTPS 요청·callback 검증은 그대로 사용한다.
