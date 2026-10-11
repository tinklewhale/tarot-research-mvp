# GitHub Actions

This setup can run the tarot research pipeline without keeping the Mac awake.

## What it does

The workflow in `.github/workflows/weekly-research-pages.yml`:

1. Runs every Monday at 09:05 Asia/Seoul.
2. Runs `scripts/run_pipeline.py`.
3. Writes results to Google Sheets.
4. Generates a static summary page with `scripts/generate_site.py`.
5. Uploads the generated HTML as a GitHub Actions artifact.

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

Pages is not available for this private repository on the current plan. The workflow still runs the automation and writes to Google Sheets. The generated HTML dashboard is stored as an Actions artifact instead of being deployed as a public web page.

## Run manually

In GitHub:

1. Open the repository.
2. Go to `Actions`.
3. Select `Weekly tarot research`.
4. Click `Run workflow`.

After the run completes, open the run details and download the `tarot-research-dashboard` artifact to view the generated HTML dashboard.

## Enabling GitHub Pages later

If the repository becomes public or the account plan supports private repository Pages, restore Pages deployment by replacing the artifact upload step with:

```yaml
- name: Configure Pages
  uses: actions/configure-pages@v5

- name: Upload Pages artifact
  uses: actions/upload-pages-artifact@v3
  with:
    path: site

- name: Deploy to GitHub Pages
  id: deployment
  uses: actions/deploy-pages@v4
```
