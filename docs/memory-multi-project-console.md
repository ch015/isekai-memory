# 전체 프로젝트 콘솔 후속 개선

다음 목표는 [M10 공용 키·중앙 프로젝트/활동 관리](memory-m10-shared-workspace-plan.md)이며
아직 계획 단계다. 아래는 기존 로컬 연결 목록 구현의 기록이다.

2026-09-15. Core의 `isekai watch` 기본 진입점을 전역 프로젝트 연결 목록으로 확장했다.

- 미등록 상태에서 오류 대신 연결 등록 화면 제공.
- 프로젝트별 Memory endpoint / 조직 / 프로젝트 / credential_ref를 등록·수정·해제.
- 등록된 여러 프로젝트의 작업·인수함·관측 사용자·보고 토큰을 페이지 단위 조회.
- 선택 프로젝트의 기존 상세·관리·작업 화면 진입, Ctrl+P로 목록 복귀.
- 서버 권한·토큰 스코프는 그대로 적용. Nunchi 로그인·프로젝트 발견·새 RBAC은 별도 후속 작업.
- Memory 서버 API·DB migration·인증 코드는 이번 변경에 포함하지 않았다.

자세한 명령, JSON 예시, 키, 제한은 Core 저장소의
`docs/memory-projects-console.md`를 참조한다.
현재 폴더의 단일 프로젝트를 직접 보려면 `isekai --project . watch`를 사용한다.
기본 목록은 `~/.config/isekai/memory-projects.json`이며 XDG_CONFIG_HOME을 지원한다.
"전체"는 등록된 연결 전체이지 서버의 모든 프로젝트를 권한 없이 조회한다는 뜻이 아니다.

## 검증

`tests/core_projects_e2e_smoke.py`는 기존 `tests/run_local_e2e.py`의
`MEMORY_CORE_CONSOLE_TESTS=1` 경로에 포함된다. 임시 프로젝트 키 2개와
허용되지 않은 별도 대상 1개를 사용하여 다음을 실제 HTTP로 확인한다.

- 두 프로젝트의 개별 조회와 실패한 연결의 격리.
- 기존 project 범위 관리자 제한 유지.
- Core의 전역 --once JSON 및 Textual 목록·상세 선택.
- 프로젝트 조회 중 서버 변경 도구 호출 없음, Core 프로젝트 초기화·State 생성 없음.

기존 M9 완료 기록은 당시 검증 결과이며, 이 후속 확장과 구분한다.
운영 서버 배포, 실제 연결 등록, Nunchi 로그인은 수행하지 않았다.
