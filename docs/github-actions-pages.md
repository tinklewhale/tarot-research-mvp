# GitHub Actions and Pages

This setup can run the tarot research pipeline without keeping the Mac awake.

## What it does

The workflow in `.github/workflows/weekly-research-pages.yml`:

1. Runs every Monday at 09:05 Asia/Seoul.
2. Runs `scripts/run_pipeline.py`.
3. Writes results to Google Sheets.
4. Generates a static summary page with `scripts/generate_site.py`.
5. Deploys the page to GitHub Pages.

The workflow can also be run manually from the GitHub Actions tab.

## Required GitHub secrets

Repository settings need these secrets:

- `YOUTUBE_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

Optional Instagram secrets:

- `INSTAGRAM_ACCESS_TOKEN`
- `INSTAGRAM_IG_USER_ID`

`GOOGLE_SERVICE_ACCOUNT_JSON` should contain the full JSON text from `secrets/google-service-account.json`.

## GitHub Pages note

GitHub Pages is available for public repositories on GitHub Free. For private repositories, GitHub Pages may require GitHub Pro, Team, or Enterprise depending on the account plan.

If Pages is not available for this private repository, the scheduled workflow can still write to Google Sheets. In that case, remove or disable the Pages deployment steps.

## Enable Pages

In GitHub:

1. Open the repository settings.
2. Go to `Pages`.
3. Set source to `GitHub Actions`.
4. Run `Weekly tarot research and Pages` manually once.

