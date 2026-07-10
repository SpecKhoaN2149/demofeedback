# Deploying the Spectrum Feedback dashboard (24/7 on Render)

This app runs as a **single always-on web service**: FastAPI serves both the
REST API and the built React dashboard on one origin, backed by a SQLite
database on a **persistent disk**. The NLP enrichment uses the Google Gemini
API.

## What's in the box

- `Dockerfile` — builds the frontend, then runs the backend serving it.
- `render.yaml` — Render Blueprint (web service + 1 GB disk + env vars).
- `.dockerignore` — keeps local DBs/secrets/venvs out of the image.

## One-time prerequisites

1. Push this repo to GitHub/GitLab (Render deploys from a connected repo).
2. Have your **Gemini API key** ready.
3. Decide the **admin username/password** your team will log in with.

## Deploy steps (Render Blueprint)

1. Go to the [Render dashboard](https://dashboard.render.com/) → **New** →
   **Blueprint**, and select this repository. Render reads `render.yaml`.
2. When prompted, fill in the secret env vars (they are `sync: false`, so Render
   asks for them):
   - `GEMINI_API_KEY` — your Gemini key
   - `ADMIN_USERNAME` — the login username for your team
   - `ADMIN_PASSWORD` — a strong password (this replaces the old admin/admin123)
3. Click **Apply**. Render builds the Docker image, mounts a 1 GB disk at
   `/data`, and starts the service. First build takes a few minutes.
4. When it's live, open the service URL (e.g. `https://spectrum-feedback.onrender.com`).
   - Dashboard/login: `https://<your-url>/admin/login`
   - Public feedback form: `https://<your-url>/`
   - Health check: `https://<your-url>/health`

That URL is now reachable 24/7 for your team.

## Environment variables

| Variable | Purpose | Example |
| --- | --- | --- |
| `GEMINI_API_KEY` | Gemini auth for NLP enrichment | *(secret)* |
| `ADMIN_USERNAME` | Admin login (seeded on startup) | `spectrum-admin` |
| `ADMIN_PASSWORD` | Admin password (seeded on startup) | *(strong secret)* |
| `SUBMISSIONS_DB_PATH` | SQLite file on the persistent disk | `/data/submissions.db` |
| `GEMINI_MODEL_PRIORITY` | Model fallback order | `gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-2.5-flash` |
| `FRONTEND_ORIGIN` | Only needed if hosting the frontend separately | `https://app.example.com` |

The admin account is (re)created from `ADMIN_USERNAME`/`ADMIN_PASSWORD` on every
startup, so to rotate the password just change the env var and redeploy.

## Run it locally as one service (optional sanity check)

```bash
docker build -t spectrum-feedback .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e ADMIN_USERNAME=admin -e ADMIN_PASSWORD=change-me \
  -e SUBMISSIONS_DB_PATH=/data/submissions.db \
  -v "$(pwd)/localdata:/data" \
  spectrum-feedback
# open http://localhost:8000
```

## Backing up the database

All feedback, tickets, and comments live in the single SQLite file on the
persistent disk (`/data/submissions.db`). Back it up regularly so a disk problem
or accidental deletion doesn't lose data.

**Use SQLite's online backup**, not a plain file copy — the app writes in WAL
mode, so copying the `.db` file alone can miss recent writes or capture a
half-written state. The online backup produces a consistent snapshot even while
the app is running.

The runtime image ships Python (not the `sqlite3` CLI), so use the stdlib
backup API — this works from the container shell as-is:

```bash
# From a shell on the running service (Render dashboard → service → "Shell"):
python -c "import sqlite3,datetime; \
src=sqlite3.connect('/data/submissions.db'); \
dst=sqlite3.connect('/data/backup-%s.db' % datetime.date.today()); \
src.backup(dst); dst.close(); src.close(); print('backup done')"
```

(If you're on a VM with the `sqlite3` CLI installed, the equivalent is
`sqlite3 /data/submissions.db ".backup '/data/backup-$(date +%F).db'"`.)

Then download the snapshot (Render dashboard → **Disks** → browse/download, or
`scp`/rsync on a VM), or push it to object storage (S3/GCS/Backblaze):

```bash
# Example: copy the latest snapshot off the box to S3 (requires AWS CLI + creds)
aws s3 cp "/data/backup-$(date +%F).db" "s3://YOUR_BUCKET/venting-machine/"
```

### Automating it

- **Render Cron Job**: add a scheduled job (its own service) that mounts the
  same disk and runs the `.backup` + upload commands daily. Point it at the same
  `/data` disk and give it your storage credentials as env vars.
- **VM (cron)**: drop the two commands into a script and schedule it, e.g.
  `0 3 * * * /opt/venting-machine/backup.sh` for a daily 03:00 backup.
- Keep a rolling window (e.g. delete snapshots older than 30 days) so backups
  don't fill the disk.

### Restoring

Stop the service (or scale to zero), then replace the live DB with a snapshot
and restart:

```bash
cp /data/backup-YYYY-MM-DD.db /data/submissions.db
# remove stale WAL/SHM sidecars so SQLite rebuilds them from the restored file
rm -f /data/submissions.db-wal /data/submissions.db-shm
```

## Notes & gotchas

- **Persistence:** the SQLite file must stay on the mounted disk (`/data`). If
  you remove the disk or point `SUBMISSIONS_DB_PATH` elsewhere, data is lost on
  redeploy. Take periodic copies of `/data/submissions.db` for backups.
- **Scaling:** SQLite is great for a single always-on instance and a small
  team. Do **not** scale this service to multiple instances — they can't share
  the SQLite file. If you outgrow it, migrate to Postgres.
- **Seed/mock data** does **not** ship to production (the local `submissions.db`
  is excluded). Production starts with an empty database that fills as real
  feedback arrives.
- **Costs:** Render's `starter` plan is always-on. The `free` plan sleeps when
  idle (cold starts), which is usually not what you want for a team dashboard.
