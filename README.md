# FAQ Telegram Bot

Answers frequently asked questions in a group chat by matching messages
against a curated set of entries stored in Firestore. Admins manage entries
through DM commands (`/add`, `/import`, `/export`, ...); the bot itself only
needs to be added to a group and given permission to read messages there.
Not tied to any particular community or domain — the FAQ content is entirely
up to whoever configures it.

## Local development

Requires Python 3.12 (3.10+ works for running the test suite; use 3.12 for
parity with the Docker image).

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements-dev.txt
cp .env.example .env          # fill in TELEGRAM_BOT_TOKEN, FIRESTORE_PROJECT_ID, etc.
```

Run the test suite (no live Telegram or Firestore connection needed — the repo
layer is exercised through an in-memory fake, see `tests/fakes.py`):

```bash
pytest
```

`tests/fixtures/faq_example.md` is a small, fully fictional example dataset
in the strict import format — useful both as import test fixtures and as a
template for writing your own content.

### Firestore emulator tests (optional)

`tests/test_firestore_emulator.py` runs the same repo layer against a real
Cloud Firestore emulator instead of the in-memory fake — it catches actual
wire-format bugs (field encoding, `.update()`-requires-existing-doc
semantics) that `FakeStore` structurally can't, since it's just a plain
dict store with no serialization layer.

It's opt-in twice over — a bare `pytest` never runs it, even on a machine
that has `firebase-tools` installed — and self-skipping. The rest of the
suite, CI, and the Docker image never need this. To actually run it:

```bash
npm install -g firebase-tools   # needs a JDK 21+ runtime
RUN_FIRESTORE_EMULATOR_TESTS=1 pytest tests/test_firestore_emulator.py
```

The emulator auto-starts once per test session and shuts down after. If
`firebase` isn't on PATH, or the emulator doesn't come up (usually an old
JDK — check with `java -version`), the module just skips with a clear
reason instead of failing the run.

Run the bot against real Telegram/Firestore once `.env` and
`GOOGLE_APPLICATION_CREDENTIALS` are set:

```bash
python -m app.main
```

`/ping` in a DM with the bot should reply `pong (<env>, <git sha>)`.

## Docker

```bash
docker compose up --build
```

Mounts `./secrets` (the Firestore service-account JSON) read-only into the
container at `/run/secrets`; point `GOOGLE_APPLICATION_CREDENTIALS` in `.env`
at the mounted path.

## Deploying to a DigitalOcean droplet

Target: Ubuntu 24.04, 1 GB. Docker + the Compose plugin installed.

### 1. GCP service account

Create a service account with **Firestore User** role only (not Editor/Owner —
the bot only needs read/write on the `faq_entries`, `admins`, `config`,
`match_log`, `miss_log`, and `feedback` collections):

```bash
gcloud iam service-accounts create faq-bot --display-name="FAQ bot"
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:faq-bot@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
gcloud iam service-accounts keys create key.json \
  --iam-account=faq-bot@<PROJECT_ID>.iam.gserviceaccount.com
```

On the droplet:

```bash
mkdir -p /opt/faq-bot/secrets
mv key.json /opt/faq-bot/secrets/firestore-sa.json
chmod 600 /opt/faq-bot/secrets/firestore-sa.json
```

**Never commit this file** — `.gitignore` already excludes `secrets/`.
Point `GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firestore-sa.json` in `.env`
(that's where `docker-compose.prod.yml` mounts `./secrets`).

### 2. Deploy

```bash
git clone <repo> /opt/faq-bot
cd /opt/faq-bot
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN, FIRESTORE_PROJECT_ID, ADMIN_USER_ID
./deploy/deploy.sh     # git pull --ff-only, build, up -d, prune — idempotent, safe to re-run
```

`docker-compose.prod.yml` adds a healthcheck (reads the liveness file
`touch_liveness_file()` writes every 30s) and `restart: unless-stopped`.

### 3. Start on boot (systemd, belt-and-braces alongside the restart policy)

```bash
sudo cp deploy/faq-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now faq-bot.service
```

### 4. Nightly backups

`scripts/backup.py` dumps every entry to `/opt/faq-bot/backups/faq_backup_<ts>.md`
(the same strict block format as `/export`) and keeps the last 14. Add to root's
crontab:

```cron
0 3 * * * /opt/faq-bot/deploy/backup.sh >> /opt/faq-bot/backups/backup.log 2>&1
```

### 5. BotFather checklist

- `/setprivacy` → **Disable** — required for the bot to read group messages
  it wasn't @mentioned in. Without this, autoreply silently never fires.
  Re-add the bot to the group after changing this.
- `/setcommands` — register only the public commands group members should see:
  ```
  faq - Переглянути список питань
  ```
  (admin commands stay undocumented/DM-only — no need to expose `/add`,
  `/import`, `/stats` etc. in the public command list.)
- Add the bot to the group, and grant it delete-message rights if you want
  the `/faq` menu auto-delete to actually work.
