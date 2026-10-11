# GitHub Actions and Pages

This setup can run the tarot research pipeline without keeping the Mac awake.

## What it does

The workflow in `.github/workflows/weekly-research-pages.yml`:

1. Runs every Monday at 09:05 Asia/Seoul.
2. Runs `scripts/run_pipeline.py`.
3. Writes results to Google Sheets.
4. Fetches the latest Claude weekly crawl sheet with `scripts/fetch_claude_crawl.py` (best effort).
5. Downloads Korean auto-captions and analyzes reading style with `scripts/analyze_transcripts.py` (best effort).
6. Generates a static summary page with `scripts/generate_site.py`.
7. Deploys the page to GitHub Pages.

The workflow can also be run manually from the GitHub Actions tab.

## Claude weekly crawl section

The dashboard shows the output of the Claude cloud routine **"주간 타로 크롤링 (월요일 아침)"**
(https://claude.ai/code/routines). Every Monday that routine uploads a Google Sheet named
`레타 주간 타로 크롤링_YYYY-MM-DD` with four tabs (`raw_crawl`, `topic_classification`,
`content_ideas`, `summary`) into the Drive folder "주간 타로 크롤링"
(`1_5FYHF5haixRGH8Dh-jolrwWf3jivOjz`).

`scripts/fetch_claude_crawl.py` reads the newest sheet with the same service account the
pipeline uses and writes `data/claude_weekly_tarot.json`. `scripts/generate_site.py` then renders:

- run date, link to the sheet and the Drive folder, collection mode (YouTube API vs WebSearch fallback)
- 수집 / 분석 포함 / 제외 / 아이디어 counts
- 이번 주 3대 발견 and 1순위 추천 (from the `summary` tab)
- content ideas sorted by `priority_score`
- keyword scoreboard (included / collected per keyword, views when available)
- `raw_crawl` table (excluded rows hidden, sorted by views when available)
- links to previous weekly sheets in the folder

### One-time Google setup (required)

The service account can only read the folder after these two steps:

1. Enable the **Google Drive API** for the service-account project:
   https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project=677283905592
   (the Sheets API is already enabled; Drive is needed to list the folder).
2. Share the Drive folder "주간 타로 크롤링" with the service account as **Viewer**:
   `tarot-general-reading-contents@tarot-general-reading-contents.iam.gserviceaccount.com`
   (the email is `client_email` in the service account JSON).

Until both are done the workflow step `Fetch Claude weekly crawl sheet` fails with a hint and the
dashboard shows a placeholder section. The step uses `continue-on-error`, so the rest of the
dashboard still deploys.

### Optional variables

Repository `Variables` (not secrets):

- `CLAUDE_CRAWL_DRIVE_FOLDER_ID` — override the folder (defaults to the folder above)
- `CLAUDE_CRAWL_SPREADSHEET_ID` — pin one specific sheet instead of using the newest

### Manual fallback

The routine also sends the xlsx to the chat. To render it without Drive access:

```bash
python scripts/fetch_claude_crawl.py --xlsx "~/Downloads/레타_주간_타로_크롤링_2026-10-05.xlsx"
python scripts/generate_site.py
```

`data/claude_weekly_tarot.example.json` shows the JSON schema (`schema_version: 2`). The older
hand-written `{summary, items[]}` format is still rendered for backwards compatibility.

## Transcript reading analysis

`scripts/analyze_transcripts.py` collects every included YouTube video from the latest pipeline output and
the Claude crawl, downloads the Korean transcript (manual captions first, then auto-generated) with
`youtube-transcript-api`, and asks OpenAI (`OPENAI_API_KEY`, `OPENAI_MODEL`) for a fixed-schema analysis of
how the reader runs the reading. The cache `data/transcript_analysis.json` is keyed by video id and is
committed to the repo.

The dashboard renders a **리딩 분석** toggle under each video title (both the Claude `raw_crawl` table and the
pipeline's 최근 분류 콘텐츠 table) and a **이번 주 리딩 패턴** block (card-selection method split, average card
count, tone distribution, common opening hooks, letter-concept takeaways).

Agent mode (no API key): `--no-llm` caches captions only, `--list-pending` dumps them to `output/transcripts/<id>.txt`
and prints the expected schema, and `--apply <json>` merges analyses a Claude session wrote by hand
(`{video_id: analysis}`), marking them `status: ok`. This is how the analysis runs on a subscription-only setup.

Caveat: YouTube frequently blocks caption downloads from datacenter IPs, so the Actions step is
`continue-on-error`. When blocked, the committed cache is what gets rendered. Run the script locally once a
week and commit the cache to keep the dashboard populated. Workflow permissions are `contents: read`, so the
runner never pushes cache updates itself.

## Two workflows

- `weekly-research-pages.yml` (Mondays 09:05 KST): runs the pipeline, then builds and deploys the dashboard.
- `deploy-dashboard.yml` (on push to the default branch touching `data/transcript_analysis.json` or the site
  scripts, or manual): rebuilds and deploys the dashboard **without** re-running the pipeline. It reads the
  pipeline data from the Google Sheet `*_latest` tabs (`generate_site.py --pipeline-source sheet`), so no
  duplicate rows are written to the sheet. This is what publishes the transcript analyses the local Mac task pushes.

## Subscription-only LLM setup (no API keys)

Both the pipeline classification and the transcript analysis can run without OpenAI/Anthropic API keys:

- **Cloud routine** (Mondays 10:00 KST, runs on the Claude subscription): reads the pipeline sheet, writes
  `topic_classification` / `content_ideas` / `summary`, and *tries* to download captions and add a
  `reading_analysis` tab. The cloud sandbox may block YouTube; then it skips. `fetch_claude_crawl.py` merges
  that tab into `data/transcript_analysis.json` when present.
- **Local scheduled task** "주간 타로 자막 분석" (Claude desktop app, Mondays 11:00 KST, needs the Mac awake):
  downloads captions on the Mac, the session itself writes the analyses (`--list-pending` -> `--apply`),
  commits `data/transcript_analysis.json` and pushes, which triggers `deploy-dashboard.yml`.

## Routine timing

The Claude routine "주간 타로 크롤링 (월요일 아침)" runs Mondays at 01:00 UTC (10:00 KST), after this
workflow (00:05 UTC). It reads the `raw_posts_latest` / `classified_topics_latest` tabs the pipeline writes
instead of calling the YouTube API itself, then uploads its weekly sheet to Drive for the dashboard to pick up.

## LLM provider

Classification, weekly ideas and transcript analysis all go through `scripts/llm_client.py`, which talks to
either OpenAI (`OPENAI_API_KEY`, `OPENAI_MODEL`) or the Claude API (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
default `claude-opus-5-5`). Pick one with the repository variable `LLM_PROVIDER` (`openai` or `anthropic`);
when unset, OpenAI is used if its key exists, otherwise Claude. If neither key works the pipeline falls back
to keyword heuristics (most posts land in 기타) and transcript analysis is skipped, so keep one provider funded.

## Required GitHub secrets

Repository settings need these secrets:

- `YOUTUBE_API_KEY`
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (see LLM provider above)
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

Optional Instagram secrets:

- `INSTAGRAM_ACCESS_TOKEN`
- `INSTAGRAM_IG_USER_ID`

`GOOGLE_SERVICE_ACCOUNT_JSON` should contain the full JSON text from `secrets/google-service-account.json`.

## GitHub Pages note

GitHub Pages is available for public repositories on GitHub Free. For private repositories, GitHub Pages may require GitHub Pro, Team, or Enterprise depending on the account plan.

The repository is public, so GitHub Pages can publish the generated dashboard without a paid GitHub plan.

## Enable Pages

In GitHub:

1. Open the repository.
2. Go to `Settings` > `Pages`.
3. Set source to `GitHub Actions`.
4. Go to `Actions`.
5. Select `Weekly tarot research and Pages`.
6. Click `Run workflow`.
