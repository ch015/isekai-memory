# ADE 프로젝트 디렉터리 검증 — 2026-09-16

U30: migration 014, 소유/할당 프로젝트 목록, 구성 등록·조회, 사용자 할당과 revision 검사.
기존 project-scoped 토큰은 그대로 제한한다. 명시적인 projects scope는 owner/member 역할과 교차 검사한다.
디렉터리가 없던 기존 Memory namespace는 해당 프로젝트의 admin만 등록할 수 있다.

검증은 macOS의 독립 PostgreSQL 14 임시 cluster에서 migration 001→014를 적용한 뒤 실행했다.
`test_project_directory.py`, `test_project_directory_postgres.py`, `test_experience_postgres.py`, `test_server.py`:
**46 통과**. 소유권·할당·회수·revision 충돌·read 역할·기존 토큰 제한·legacy namespace 보호·기존 인계/기억 동작을 포함한다.
변경 서버 파일 Ruff 검사 통과. Python 3.14의 pytest-asyncio 경고는 실패가 아니며 서버 인수와 구분한다.

ADE의 실제 Electron 두 인스턴스와 이 서버·PostgreSQL·HTTPS Git fixture를 이용한 테스트에서도
등록→할당→clone→CORE 복원→설정 오류 후 재시도가 통과했다. 외부 운영 서버나 실제 사용자 Git/CLI 계정을 검증한 것은 아니다.

운영 반영에는 서버 배포, `python -m alembic upgrade head`, 적절한 프로젝트 토큰 발급이 별도로 필요하다.
이 작업은 사용자 운영 서버를 배포하거나 마이그레이션하지 않았다. `.isekai/`, `reports/`의 기존 로컬 파일은 변경하지 않았다.
API·운영자 전환 절차는 [ade-project-directory.md](ade-project-directory.md)를 따른다.
