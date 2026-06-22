# 바이럴 트래커 — 설정 가이드

## 지금 적용된 검색 키워드
- AI short film dystopia
- AI cinematic sci-fi short
- horror short film viral
- thriller short film viral

`tracker.py` 상단 `SEARCH_KEYWORDS` 리스트에서 자유롭게 추가/수정 가능. 다양하게 돌려보다가 나중에 좁히면 됨.

## 판단 기준
"조회수 ÷ 구독자수 ≥ 5.0" 인 영상만 후보로 잡힘 (구독자 적은데 조회수 비정상적으로 높은 영상).
→ `tracker.py`의 `ANOMALY_THRESHOLD` 값으로 민감도 조절 가능 (낮추면 후보 더 많이 잡힘, 높이면 더 엄격해짐).

---

## 1단계 — GitHub 저장소 만들기
1. github.com 접속 → 로그인 → 우측 상단 "+" → "New repository"
2. 이름: `viral-tracker` (Private 선택 — 키 노출 방지)
3. `tracker.py`와 `.github/workflows/tracker.yml` 파일을 그대로 업로드 (폴더 구조 그대로 유지해야 함)

## 2단계 — GitHub Secrets 등록 (API 키를 안전하게 저장하는 곳)
1. 저장소 페이지 → Settings → Secrets and variables → Actions
2. "New repository secret" 클릭
3. 이름: `YOUTUBE_API_KEY` / 값: 발급받은 키 붙여넣기 → 저장
4. (Sheets 자동 저장 원하면) 이름: `GOOGLE_SHEETS_CREDENTIALS` / 값: 서비스 계정 JSON 전체 내용 붙여넣기

> Sheets 연결 안 하면 4번은 생략 가능 — 이 경우 결과는 저장소 안 `results.csv` 파일에 자동 누적됨 (저장소 들어가서 파일만 열어보면 확인 가능).

## 3단계 — 실행 확인
1. 저장소 → "Actions" 탭 → "YouTube Viral Tracker" 워크플로우 선택
2. "Run workflow" 버튼으로 수동 테스트 1회 실행
3. 정상 작동하면 이후 6시간마다 자동 실행됨 (스케줄 변경하려면 `tracker.yml`의 cron 값 수정)

## 4단계 (선택) — Google Sheets 자동 저장 세팅
나중에 필요해지면:
1. Cloud Console → "사용자 인증 정보 만들기" → "서비스 계정" 생성
2. 생성된 서비스 계정 → 키(JSON) 다운로드
3. 그 JSON 내용을 GitHub Secret `GOOGLE_SHEETS_CREDENTIALS`에 등록
4. Google Sheets에서 새 시트 만들고, 서비스 계정 이메일을 "편집자"로 공유 추가
5. 시트 이름을 `viral-tracker`로 맞추거나 `tracker.yml`의 `SPREADSHEET_NAME` 값 수정

이 단계는 지금 당장 안 해도 됨 — CSV로 먼저 결과 확인하다가 필요해지면 그때 진행.
