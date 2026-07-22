"""Seed the committed local demo dataset (data/) into cloud storage.

Run once after the first `cloud`-mode deploy so Firestore + GCS hold the same
demo content the app ships with locally. Idempotent: files are upserted, never
deleted. Uses the app's own storage backends, so the mapping (JSON→Firestore,
binary→GCS) is identical to what the running app does.

Usage:
    export STORAGE=cloud
    export GOOGLE_CLOUD_PROJECT=your-project
    export WAI_GCS_BUCKET=your-project-wai-data
    python scripts/seed_cloud_storage.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core import settings
from src.core.storage_backend import LocalStorageBackend, get_backend

# Extensions stored as text (Firestore) vs. everything else as bytes (GCS).
_TEXT_SUFFIXES = {".json", ".txt", ".md", ".html", ".htm", ".xml", ".csv"}

# Runtime/ephemeral or gitignored trees we never seed (regenerated at runtime).
_SKIP_DIRS = {"kpi_store", "conflicts", "quizzes", "kb_jobs", "gap_cache"}


def _is_text(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_SUFFIXES or path.name.endswith(".meta.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List what would be seeded, write nothing.")
    parser.add_argument("--data-dir", default="data", help="Local data directory to read from.")
    args = parser.parse_args()

    if not settings.is_cloud_storage():
        print("ERROR: set STORAGE=cloud (plus GOOGLE_CLOUD_PROJECT and WAI_GCS_BUCKET).")
        return 2

    data_root = Path(args.data_dir).resolve()
    if not data_root.is_dir():
        print(f"ERROR: data dir not found: {data_root}")
        return 2

    local = LocalStorageBackend(data_root)
    cloud = get_backend(data_root)  # FirestoreGcsBackend, since STORAGE=cloud

    text_count = bytes_count = skipped = 0
    for path in sorted(data_root.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        relpath = path.relative_to(data_root).as_posix()
        if any(seg in _SKIP_DIRS for seg in relpath.split("/")):
            skipped += 1
            continue

        if _is_text(path):
            text_count += 1
            kind = "firestore"
            if not args.dry_run:
                cloud.write_text(relpath, local.read_text(relpath) or "")
        else:
            bytes_count += 1
            kind = "gcs"
            if not args.dry_run:
                cloud.write_bytes(relpath, local.read_bytes(relpath) or b"")
        print(f"  [{kind:9}] {relpath}")

    verb = "Would seed" if args.dry_run else "Seeded"
    print(f"\n{verb}: {text_count} text→Firestore, {bytes_count} binary→GCS, {skipped} skipped (runtime).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
