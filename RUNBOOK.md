# WisdomAI — Deployment Runbook

This is the **mechanical, copy-paste** guide for running and deploying WisdomAI —
written so it needs **no AI assistance** to follow. All the architecture work
(containerization, a cloud storage backend, password hashing, secrets, the SSO
story) is already done in the code. This file is just "which commands to run."

> **Strategy behind this split:** the hard, one-time engineering was done up front
> (see the `STORAGE`/auth/Docker plumbing). From here on, deploying is running a
> script and pasting a few `gcloud` commands.

---

## 0. The one mental model you need

The app has **two storage modes**, chosen by the `STORAGE` env var:

| `STORAGE` | JSON data | Uploaded files (PDF/img/audio) | Needs cloud? |
|-----------|-----------|--------------------------------|--------------|
| `local` (default) | `data/**.json` on disk | `data/**` on disk | No — works offline on **either laptop** |
| `cloud` | Firestore | GCS bucket | Yes (Cloud Run / GCP) |

Nothing about `local` mode changed — the app runs exactly as it always has. `cloud`
mode is what Cloud Run uses so data survives restarts and scales.

---

## 1. Run locally (either laptop, no cloud needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set GOOGLE_CLOUD_PROJECT for Gemini calls
gcloud auth application-default login   # one-time, for Vertex/Gemini
uvicorn src.api.main:app --reload       # → http://localhost:8000
```

Login accounts (demo): `manager / manager123`, `emp_001 / alex123`,
`emp_003 / james123`, `developer / dev123`, … (passwords are bcrypt-hashed in
`data/credentials.json`; these are throwaway demo accounts).

Run the test suite (the safety net — keep it green):

```bash
python3 -m pytest tests/ -q      # expect: all passed, 2 deselected (eval/ADC)
```

---

## 2. One-time GCP setup (company laptop)

```bash
gcloud auth login                       # your company Google account
gcloud config set project YOUR_PROJECT_ID
# Billing must be enabled on the project (console → Billing).
```

That's it — `deploy.sh` enables every API and creates every resource it needs.

---

## 3. Deploy to Cloud Run (one script)

Edit the three variables at the top of **`deploy.sh`**:

```bash
PROJECT_ID="your-gcp-project-id"
REGION="europe-west1"      # a region near you
SERVICE="wisdom-ai"
```

Then run it:

```bash
./deploy.sh
```

It is **idempotent** — safe to re-run for every redeploy. On each run it:

1. Enables the required APIs (Run, Cloud Build, Artifact Registry, Firestore,
   Secret Manager, Vertex AI).
2. Creates the Firestore database (Native mode) if missing.
3. Creates the GCS bucket `PROJECT_ID-wai-data` if missing.
4. Creates the Secret Manager secret `wai-credentials` from `data/credentials.json`
   (bcrypt-hashed passwords) if missing.
5. Grants the Cloud Run service account access to the secret, Firestore, GCS, Vertex.
6. Builds the container and deploys, with `STORAGE=cloud` and all env wired up.

At the end it prints the service URL.

> Alternative CI path: `cloudbuild.yaml` does the same via a GitHub-triggered
> Cloud Build. Use it if you want push-to-deploy instead of running the script.

---

## 4. Seed the demo data into the cloud (first deploy only)

`cloud` mode starts with **empty** Firestore + GCS. To copy the committed demo
dataset (`data/`) up once:

```bash
export STORAGE=cloud
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export WAI_GCS_BUCKET=YOUR_PROJECT_ID-wai-data
python scripts/seed_cloud_storage.py       # add --dry-run first to preview
```

This walks `data/`, writing each JSON doc to Firestore and each binary to GCS
through the exact same storage backend the app uses. Re-running it re-seeds
(idempotent upserts); it never deletes anything already in the cloud.

---

## 5. Put company SSO in front of the app (Google IAP)

The app itself has demo-grade login. For **real access control using your company
Google SSO**, sit Cloud Run behind **Identity-Aware Proxy (IAP)** — Google checks
the employee's identity at the edge before any request reaches the app.

High level (see Google's "Enabling IAP for Cloud Run" doc for the current UI):

1. Put the Cloud Run service behind an external HTTPS Load Balancer (serverless NEG).
2. On that load balancer's backend, **enable IAP** and grant the
   `IAP-secured Web App User` role to the Google Group / users who may access it.
3. Redeploy the app with `--set-env-vars WAI_TRUST_IAP=true` (add it to `deploy.sh`).
   With that flag on, the app reads IAP's verified identity from the
   `X-Goog-Authenticated-User-Email` header (endpoint: `GET /api/auth/iap`).

> Leave `WAI_TRUST_IAP=false` (the default) whenever the service is **not** behind
> IAP — otherwise that header is spoofable.

**Known gap (documented, not yet done):** in-app API routes still trust a
client-supplied `role`/`user_id` (demo-grade). IAP secures *who can reach the app*
at the edge, which is the important boundary for an MVP. Tightening each route to
enforce role server-side from the IAP identity is a deliberate later task.

---

## 6. Rotate the credentials / add a user

Edit `data/credentials.json` (use `scripts/hash_password.py "newpass"` — or the
Python one-liner below — to make a hash), then push a new secret version:

```bash
python -c "from src.core.auth_store import hash_password as h; print(h('newpass'))"
gcloud secrets versions add wai-credentials --data-file=data/credentials.json
# Redeploy (or the next deploy) picks up :latest.
```

---

## 7. Verify cloud storage locally (optional, with the Firestore emulator)

You can exercise `STORAGE=cloud` without touching real GCP for Firestore:

```bash
gcloud emulators firestore start --host-port=localhost:8080
# in another shell:
export FIRESTORE_EMULATOR_HOST=localhost:8080
export STORAGE=cloud GOOGLE_CLOUD_PROJECT=demo WAI_GCS_BUCKET=demo-bucket
# (GCS has no local emulator in gcloud; use a real dev bucket for binary tests.)
```

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `STORAGE=cloud requires WAI_GCS_BUCKET` | Set `WAI_GCS_BUCKET` (deploy.sh does this automatically). |
| 403 from Firestore/GCS on Cloud Run | Re-run `deploy.sh` — it (re)grants the runtime SA the `datastore.user` + `storage.objectAdmin` roles. |
| Gemini/Vertex auth error | Confirm `GOOGLE_CLOUD_PROJECT` is set and the SA has `aiplatform.user`; locally run `gcloud auth application-default login`. |
| Login fails after editing credentials | The file needs `password_hash` (bcrypt), not plaintext — regenerate with `hash_password`. |
| Container won't start | Check `PORT` — the image binds `$PORT` (Cloud Run injects 8080). Don't hardcode a port in the CMD. |

---

## 9. Rollback

```bash
gcloud run revisions list --service wisdom-ai --region YOUR_REGION
gcloud run services update-traffic wisdom-ai --region YOUR_REGION --to-revisions REVISION=100
```
