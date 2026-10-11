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
- OpenAI API Key
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
- `.env`의 `OPENAI_API_KEY`
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

## 9. 로컬 단독 테스트

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

## 10. 운영 팁

- 처음 2주 동안은 `config/topics.json` 키워드를 계속 보정하는 게 좋습니다.
- `Threads`는 나중에 Playwright 수집기로 분리하는 편이 안전합니다.
- `Instagram`은 해시태그/시간 제한 때문에 광범위 크롤링보다 정해진 주제 풀을 반복 추적하는 방식이 맞습니다.
