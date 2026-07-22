#!/usr/bin/env bash
#
# WisdomAI MVP — one-shot Cloud Run deploy.
#
# Designed to be run on the *company laptop* with NO Claude available: edit the
# three variables in the CONFIG block, then run `./deploy.sh`. It is idempotent —
# safe to re-run; it creates cloud resources only if they don't already exist.
#
# Prerequisites (one-time, see RUNBOOK.md):
#   - gcloud CLI installed and `gcloud auth login` done
#   - billing enabled on the project
#
set -euo pipefail

# ─────────────────────────── CONFIG — EDIT THESE ────────────────────────────
PROJECT_ID="your-gcp-project-id"     # gcloud projects list
REGION="europe-west1"                # a region near you (Cloud Run + Firestore)
SERVICE="wisdom-ai"                  # Cloud Run service name
# ────────────────────────────────────────────────────────────────────────────

BUCKET="${PROJECT_ID}-wai-data"      # GCS bucket for binary blobs
SECRET="wai-credentials"             # Secret Manager secret holding credentials.json
GENAI_LOCATION="global"              # Vertex AI location for Gemini

echo "==> Project: ${PROJECT_ID}   Region: ${REGION}   Service: ${SERVICE}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "==> Enabling required APIs (no-op if already enabled)…"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com

echo "==> Ensuring Firestore database exists (Native mode)…"
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="${REGION}" --type=firestore-native
else
  echo "    Firestore (default) already exists."
fi

echo "==> Ensuring GCS bucket gs://${BUCKET} exists…"
if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" --uniform-bucket-level-access
else
  echo "    Bucket already exists."
fi

echo "==> Ensuring Secret Manager secret '${SECRET}' exists…"
if ! gcloud secrets describe "${SECRET}" >/dev/null 2>&1; then
  # Seed the secret from the local (bcrypt-hashed) credentials file.
  # After first deploy you can rotate it with: gcloud secrets versions add ...
  gcloud secrets create "${SECRET}" --replication-policy=automatic
  gcloud secrets versions add "${SECRET}" --data-file=data/credentials.json
else
  echo "    Secret already exists (leaving current version in place)."
fi

# Grant the Cloud Run runtime service account access to the secret + buckets.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "==> Granting runtime SA (${RUNTIME_SA}) access to secret + Firestore + GCS…"
gcloud secrets add-iam-policy-binding "${SECRET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/datastore.user >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/storage.objectAdmin >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/aiplatform.user >/dev/null

echo "==> Building + deploying to Cloud Run (source build)…"
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --cpu 1 --memory 1Gi --min-instances 0 --max-instances 4 \
  --set-env-vars "STORAGE=cloud,WAI_GCS_BUCKET=${BUCKET},WAI_FIRESTORE_DATABASE=(default),WAI_FIRESTORE_PREFIX=wai,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${GENAI_LOCATION}" \
  --set-secrets "WAI_CREDENTIALS_JSON=${SECRET}:latest"

echo "==> Done. Service URL:"
gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)'

cat <<'NOTE'

Next (optional) — put your company SSO in front of the app with IAP:
  1. Set the service to require auth instead of --allow-unauthenticated, OR add a
     load balancer + IAP (see RUNBOOK.md "Enable IAP / SSO").
  2. Set WAI_TRUST_IAP=true so the app reads the IAP identity header.
NOTE
