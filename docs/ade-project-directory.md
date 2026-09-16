# ADE 프로젝트 디렉터리 (schema 014)

`memory_project_list/get/register/assign`는 코드 저장소 메타데이터와 재현 가능한 CORE 구성을 관리한다.
Git 저장소 자체, 인증키, 로컬 State DB, 터미널 출력은 저장하지 않는다. 적용 전 `alembic upgrade head`가 필요하다.

기존 project-scoped 토큰은 해당 프로젝트에만 접근한다. 여러 할당 프로젝트를 조회/사용하려면 서버 운영자가
명시적으로 `--scopes read,write,projects` 토큰을 발급한다. `--project-id directory`는 이 토큰의 발급 표시값으로
사용할 수 있다. `projects` 권한이 있는 토큰도 owner/member 행이 없는 기존 프로젝트에 접근할 수 없으며,
member의 read/write 역할과 토큰 자체 scope의 교집합만 허용한다. 새 프로젝트 등록자는 owner다.
기존 토큰에 자동으로 권한을 추가하지 않으며, Git 인증은 별도다.

디렉터리 도입 전에 토큰·인계·기억·정책 등 서버 데이터가 이미 있는 project_id는 전역 `projects` 토큰으로 선점할 수 없다.
해당 프로젝트에 제한된 기존 admin 토큰(또는 로컬 운영자)으로 먼저 등록한 뒤 필요한 사용자를 할당한다.

- list: 인증된 actor가 소유하거나 할당받은 프로젝트를 ID cursor로 페이지 조회한다.
- get: clone URL/ref와 revision, `setup` manifest를 반환한다.
- register: 처음에는 expected_revision=0. 변경은 관측한 revision 필요. 동일 내용 재전송은 멱등이다.
- assign: owner가 대상 user_id에 read/write를 부여하거나 remove한다. 이미 같은 상태면 멱등이다.

setup schema 1은 config(비밀 없는 Project 설정), artifacts(kind/id/version/artifact_digest), canonical SHA-256 digest로
구성된다. ADE는 schema와 digest를 다시 검증한다. 초기 ADE는 현재 번들의 정확한 artifact digest가 모두 존재할 때만
복원한다. 사용할 수 없는 버전을 최신 버전으로 바꾸지 않는다. 패키지 원격 배포는 기존 Git Releases 경로를 유지한다.

schema 014는 전용 새 DB/로컬 PostgreSQL에서 테스트한다. 실제 사용자 서버에 자동 migration/배포하지 않는다.
