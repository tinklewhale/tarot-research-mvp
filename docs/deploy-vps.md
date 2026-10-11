# VPS Deployment

This project can run on a VPS with Docker Compose. The local Mac can be turned off after the VPS is running.

## 1. Server prerequisites

Use an Ubuntu VPS with:

- Docker
- Docker Compose
- Git
- A domain pointing to the VPS public IP

Open inbound ports:

- `80`
- `443`

## 2. Clone the private GitHub repo

```bash
git clone https://github.com/tinklewhale/tarot-research-mvp.git
cd tarot-research-mvp
git checkout codex/tarot-research-mvp
```

## 3. Create server-only secrets

```bash
cp .env.prod.example .env
mkdir -p secrets
```

Edit `.env` on the server:

```bash
nano .env
```

Set these values:

- `N8N_HOST`: your domain, for example `automation.example.com`
- `N8N_ENCRYPTION_KEY`: long random string
- `YOUTUBE_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_SHEETS_SPREADSHEET_ID`

Place the Google service account file here:

```text
secrets/google-service-account.json
```

Share the Google Sheet with the service account `client_email`.

## 4. Start production

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Then open:

```text
https://YOUR_DOMAIN
```

Create the first n8n owner account in the browser.

## 5. Import the workflow

In n8n:

1. Open `https://YOUR_DOMAIN`
2. Go to workflows
3. Import `n8n/workflows/tarot-research-mvp.json`
4. Save the workflow
5. Run it manually once
6. Turn it active if the test run succeeds

You can also import from the server CLI:

```bash
docker compose -f docker-compose.prod.yml exec -T n8n n8n import:workflow --input=/workspace/n8n/workflows/tarot-research-mvp.json
```

After CLI import, open n8n in the browser and activate the workflow.

## 6. Update after local changes

On the Mac:

```bash
git add .
git commit -m "Describe the change"
git push
```

On the VPS:

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## 7. Check status

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100
```

## Notes

- Do not commit `.env` or `secrets/`.
- The current workflow uses an Execute Command node, so the Python script must stay available in `/workspace/scripts/run_pipeline.py`.
- n8n Cloud is easier to operate, but this project uses local Python execution. Moving to n8n Cloud would require hosting the Python pipeline separately as an API endpoint.
