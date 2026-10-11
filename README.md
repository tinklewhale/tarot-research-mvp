# Tarot General Reading Research MVP

`n8n`을 스케줄러로 쓰고, 실제 수집/분류/구글시트 입력은 Python으로 처리하는 로컬 실행형 MVP입니다.

## 이 프로젝트가 하는 일

1. 매주 키워드 기준으로 `YouTube` 리서치
2. 선택적으로 `Instagram` 해시태그 리서치
3. `Threads`는 `data/manual_sources.csv`에 넣어둔 링크를 함께 처리
4. 교육형 콘텐츠 제외
5. 대주제/소주제 분류
6. 주간 콘텐츠 아이디어 생성
7. 결과를 `Google Sheets` 3개 시트에 기록

## MVP 범위

- 자동 수집: `YouTube`
- 조건부 자동 수집: `Instagram Graph API`
- 반자동 수집: `Threads`, 수동 링크 입력 후 자동 분류

`Threads`는 공식 공용 탐색 수집 제약이 커서 MVP에서는 반자동 경로로 두었습니다.

## 1. 로컬 실행 준비

### 필수

- Docker Desktop
- YouTube Data API Key
- LLM API Key 하나: OpenAI 또는 Claude(Anthropic). `.env`의 `LLM_PROVIDER`로 선택 (분류·아이디어·자막 분석에 공통 사용)
- Google service account JSON

### 선택

- Instagram Graph API Access Token
- Instagram IG User ID

## 2. 파일 준비

1. `.env.example`를 복사해서 `.env` 생성
2. `secrets/google-service-account.json` 경로에 구글 서비스 계정 키 저장
3. `config/topics.json`의 키워드 수정
4. 필요하면 `data/manual_sources.csv`에 Threads/Instagram 링크 추가

## 3. Google Sheets 준비

1. 새 구글시트를 하나 만듭니다.
2. URL에서 Spreadsheet ID를 복사합니다.
3. `.env`의 `GOOGLE_SHEETS_SPREADSHEET_ID`에 넣습니다.
4. 서비스 계정 이메일에 시트 편집 권한을 줍니다.

서비스 계정 이메일은 JSON 파일 안의 `client_email`입니다.

## 4. n8n 실행

### 방법 A. Docker 사용

```bash
cp .env.example .env
mkdir -p secrets
docker compose up --build
```

브라우저에서 `http://localhost:5678` 접속 후 `.env`에 넣은 기본 인증으로 로그인합니다.

### 방법 B. Docker 없이 로컬 실행

`node`와 `npm`이 이미 있다면 이 방법이 더 빠릅니다.

```bash
cp .env.example .env
npm install
npm run n8n
```

브라우저에서 `http://localhost:5678` 접속 후 `.env`에 넣은 기본 인증으로 로그인합니다.

처음 한 번은 `npm install`에 몇 분 걸릴 수 있습니다.

## 5. 워크플로우 import

1. n8n 좌측 상단에서 `Import from file`
2. `n8n/workflows/tarot-research-mvp.json` 선택
3. 워크플로우를 저장
4. 먼저 `Test workflow`로 수동 실행
5. 이상 없으면 `Active`로 켜서 주간 실행

## 6. 첫 실행 전에 꼭 확인할 값

- `.env`의 `YOUTUBE_API_KEY`
- `.env`의 `OPENAI_API_KEY` 또는 `ANTHROPIC_API_KEY` (둘 다 없으면 키워드 휴리스틱 분류로만 동작)
- `.env`의 `GOOGLE_SHEETS_SPREADSHEET_ID`
- `secrets/google-service-account.json` 파일 존재 여부

Instagram은 아래 둘 다 있어야 실제 호출합니다.

- `INSTAGRAM_ACCESS_TOKEN`
- `INSTAGRAM_IG_USER_ID`

없으면 자동으로 건너뜁니다.

## 7. Threads 입력 방식

`data/manual_sources.csv`에 아래 같은 형식으로 링크를 넣으면 같이 분류됩니다.

```csv
platform,keyword,title,description,hashtags,author,published_at,url,views,likes
threads,재회 타로,그 사람 연락 올까요?,댓글 Pick a card,#재회타로 #속마음,example_reader,2025-04-10T09:00:00+09:00,https://www.threads.net/@example/post/123,0,0
```

## 8. 결과 시트

- `raw_posts`: 원본 수집 데이터
- `classified_topics`: 대주제/소주제 분류 결과
- `weekly_ideas`: 이번 주 콘텐츠 아이디어

시트가 없으면 자동 생성합니다.

## 9. 대시보드 + Claude 주간 크롤링 연동

`scripts/generate_site.py`가 만드는 정적 대시보드(`site/index.html`)는 GitHub Pages로 배포됩니다
(`docs/github-actions-pages.md`). 대시보드에는 이 레포 파이프라인 결과 외에, 클로드 예약 작업
**「주간 타로 크롤링 (월요일 아침)」**이 구글 드라이브 '주간 타로 크롤링' 폴더에 올리는 주간 시트
(`레타 주간 타로 크롤링_YYYY-MM-DD`, 탭: raw_crawl / topic_classification / content_ideas / summary)도 함께 표시됩니다.

```text
Claude 루틴 (매주 월 09:00) ──▶ Google Drive '주간 타로 크롤링' 시트
                                        │
GitHub Actions (매주 월 09:05) ─▶ fetch_claude_crawl.py ─▶ data/claude_weekly_tarot.json
                                        │
                     run_pipeline.py ─▶ generate_site.py ─▶ GitHub Pages
```

최초 1회 설정 (서비스 계정이 폴더를 읽을 수 있어야 합니다):

1. GCP 프로젝트에서 Google Drive API 활성화
2. 드라이브 폴더 '주간 타로 크롤링'을 서비스 계정 이메일(`client_email`)에 뷰어로 공유

로컬에서 확인하려면:

```bash
python3 scripts/fetch_claude_crawl.py
python3 scripts/generate_site.py
open site/index.html
```

드라이브 접근이 아직 안 되면 루틴이 채팅으로 보내준 xlsx를 직접 변환할 수 있습니다:

```bash
python3 scripts/fetch_claude_crawl.py --xlsx ~/Downloads/레타_주간_타로_크롤링_2026-10-05.xlsx
```

### 9-1. 클로드 루틴과 파이프라인의 역할 분담

- 파이프라인(Actions, 월 09:05)이 YouTube Data API로 수집·분류하고 시트의 `raw_posts` / `classified_topics` / `weekly_ideas`에 누적 기록합니다. 같은 내용을 이번 주 분량만 담은 `*_latest` 탭에도 덮어씁니다.
- 클로드 루틴(월 10:00)은 YouTube API를 직접 부르지 않고 `*_latest` 탭을 읽어 레타 편지 컨셉 아이디어와 3대 발견을 만든 뒤 드라이브에 주간 시트를 올립니다. YouTube API 키는 GitHub 시크릿 `YOUTUBE_API_KEY` 한 곳에만 둡니다.

## 10. 유튜브 자막 리딩 분석

`scripts/analyze_transcripts.py`가 이번 주 영상(파이프라인 + 클로드 루틴, 분석 포함 건)의 한국어 자동 자막을 키 없이 내려받고,
OpenAI로 "리더가 리딩을 어떻게 진행하는지"를 고정 항목으로 분석합니다(오프닝 훅, 카드 선택 연출, 진행 구조, 톤, 반복 표현, 참여 유도, CTA, 편지 컨셉 적용 포인트).
결과는 `data/transcript_analysis.json`에 영상 ID별로 캐시되고, 대시보드에서는 각 영상 행의 **리딩 분석** 토글과 섹션 상단의 **이번 주 리딩 패턴** 블록으로 표시됩니다.

```bash
python3 scripts/analyze_transcripts.py            # 새 영상만 분석 (기본 60개)
python3 scripts/analyze_transcripts.py --limit 10
python3 scripts/analyze_transcripts.py --no-llm   # 자막만 받아두기
python3 scripts/analyze_transcripts.py --retry-errors
python3 scripts/generate_site.py && open site/index.html
```

API 키 없이 구독만 있을 때(에이전트 모드): 스크립트는 자막만 받아 두고, 클로드 세션이 직접 읽고 분석을 써넣습니다.

```bash
python3 scripts/analyze_transcripts.py --no-llm          # 1) 자막만 캐시에 저장
python3 scripts/analyze_transcripts.py --list-pending    # 2) output/transcripts/<id>.txt 로 꺼내고 목록·스키마 출력
# 3) 클로드가 각 txt를 읽고 {video_id: analysis} JSON을 작성
python3 scripts/analyze_transcripts.py --apply analyses.json   # 4) 캐시에 병합 (status ok)
python3 scripts/generate_site.py
```

주의: 자막 다운로드는 유튜브 비공식 경로라 GitHub Actions 같은 데이터센터 IP에서는 차단될 수 있습니다. Actions 단계는 best-effort이고,
맥에서 주 1회 위 명령을 돌린 뒤 `data/transcript_analysis.json`을 커밋하면 대시보드가 항상 채워집니다. OpenAI 호출 비용은 영상당 자막 1.4만 자 기준으로 매우 적습니다.

### 10-1. 구독만으로 돌아가는 운영 구성 (API 키 없음)

```text
월 09:05  GitHub Actions  파이프라인 수집(YouTube API) → 시트 *_latest 탭 → 대시보드 배포
월 10:00  클라우드 루틴   시트 읽기 → 분류·아이디어·3대 발견 → 드라이브 주간 시트 (+ 가능하면 reading_analysis 탭)
월 11:00  로컬 예약 작업  맥에서 자막 다운로드 → 세션이 직접 리딩 분석 → data/transcript_analysis.json 커밋·푸시
푸시 직후 GitHub Actions  deploy-dashboard.yml 이 시트에서 데이터를 읽어 대시보드만 다시 배포
```

- 로컬 예약 작업은 클로드 데스크톱 앱이 열려 있을 때 실행됩니다. 꺼져 있으면 다음 실행 때 돌고, 그 주는 클라우드 루틴이 성공한 만큼만 분석이 표시됩니다.
- 대시보드만 다시 만들 때는 `python3 scripts/generate_site.py --pipeline-source sheet`로 파이프라인 결과를 시트에서 읽습니다.

## 11. 로컬 단독 테스트

컨테이너 없이 파이프라인만 시험하려면:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/run_pipeline.py
```

`n8n`만 먼저 확인하고 싶다면:

```bash
npm run n8n
```

그 다음 브라우저에서 `http://localhost:5678`가 열리면 정상입니다.

## 12. 운영 팁

- 처음 2주 동안은 `config/topics.json` 키워드를 계속 보정하는 게 좋습니다.
- `Threads`는 나중에 Playwright 수집기로 분리하는 편이 안전합니다.
- `Instagram`은 해시태그/시간 제한 때문에 광범위 크롤링보다 정해진 주제 풀을 반복 추적하는 방식이 맞습니다.
