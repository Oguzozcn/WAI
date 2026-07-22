"""Pluggable storage backend under the DepartmentScopedStore seam.

`DepartmentScopedStore` owns all the *domain* logic (path/key construction,
ordering, filtering, the KPI/version-history rules). It performs its actual
leaf I/O through one of these backends, chosen by the STORAGE env var:

    STORAGE=local  -> LocalStorageBackend    (filesystem under data/, the default)
    STORAGE=cloud  -> FirestoreGcsBackend     (JSON/text in Firestore, blobs in GCS)

Both backends speak the same tiny primitive interface keyed by POSIX-style
*relative paths* (e.g. "user_progress/operations/emp_001.json"). The local
backend maps a relpath to `base_path / relpath` — byte-for-byte the behavior the
app has always had, which is why the whole existing test suite (which runs in
local mode) keeps proving nothing regressed. The cloud backend maps the same
relpath to a Firestore document (text) or a GCS object (bytes).

Text vs. bytes routing is unambiguous: callers always know whether they're
reading text/JSON (`read_text`/`write_text`) or binary (`read_bytes`/
`write_bytes`), so in cloud mode text lands in Firestore and blobs in GCS with
no guessing by file extension.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core import settings


class StorageBackend(ABC):
    """Relpath-keyed leaf I/O. All paths are POSIX-relative to the data root."""

    @abstractmethod
    def read_text(self, relpath: str) -> Optional[str]: ...
    @abstractmethod
    def write_text(self, relpath: str, text: str) -> None: ...
    @abstractmethod
    def read_bytes(self, relpath: str) -> Optional[bytes]: ...
    @abstractmethod
    def write_bytes(self, relpath: str, data: bytes) -> None: ...
    @abstractmethod
    def exists(self, relpath: str) -> bool: ...
    @abstractmethod
    def delete(self, relpath: str) -> bool:
        """Delete a file. Returns True if it existed."""
    @abstractmethod
    def list_files(self, reldir: str, suffix: Optional[str] = None) -> list[str]:
        """Immediate file NAMES under reldir (not recursive), sorted."""
    @abstractmethod
    def list_files_meta(self, reldir: str, suffix: Optional[str] = None) -> list[dict]:
        """Immediate files as [{'name','size','mtime'}], sorted by name."""
    @abstractmethod
    def list_dirs(self, reldir: str) -> list[str]:
        """Immediate subdirectory NAMES under reldir, sorted."""
    @abstractmethod
    def delete_dir(self, reldir: str) -> None:
        """Recursively delete everything under reldir."""

    def ensure_dirs(self, reldirs: list[str]) -> None:  # noqa: B027 - optional hook
        """Pre-create directories (local only). Cloud backends leave this a no-op."""
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Local filesystem backend — the historical behavior, kept byte-identical.
# ──────────────────────────────────────────────────────────────────────────────
class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def _p(self, relpath: str) -> Path:
        return self.base_path / relpath

    def read_text(self, relpath: str) -> Optional[str]:
        p = self._p(relpath)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_text(self, relpath: str, text: str) -> None:
        p = self._p(relpath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def read_bytes(self, relpath: str) -> Optional[bytes]:
        p = self._p(relpath)
        return p.read_bytes() if p.exists() else None

    def write_bytes(self, relpath: str, data: bytes) -> None:
        p = self._p(relpath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exists(self, relpath: str) -> bool:
        return self._p(relpath).exists()

    def delete(self, relpath: str) -> bool:
        p = self._p(relpath)
        if not p.exists():
            return False
        p.unlink()
        return True

    def list_files(self, reldir: str, suffix: Optional[str] = None) -> list[str]:
        d = self._p(reldir)
        if not d.exists():
            return []
        return sorted(
            f.name for f in d.iterdir()
            if f.is_file() and (suffix is None or f.name.endswith(suffix))
        )

    def list_files_meta(self, reldir: str, suffix: Optional[str] = None) -> list[dict]:
        d = self._p(reldir)
        if not d.exists():
            return []
        out = []
        for f in d.iterdir():
            if f.is_file() and (suffix is None or f.name.endswith(suffix)):
                st = f.stat()
                out.append({"name": f.name, "size": st.st_size, "mtime": st.st_mtime})
        out.sort(key=lambda m: m["name"])
        return out

    def list_dirs(self, reldir: str) -> list[str]:
        d = self._p(reldir)
        if not d.exists():
            return []
        return sorted(sub.name for sub in d.iterdir() if sub.is_dir())

    def delete_dir(self, reldir: str) -> None:
        d = self._p(reldir)
        if d.exists():
            shutil.rmtree(d)

    def ensure_dirs(self, reldirs: list[str]) -> None:
        for rel in reldirs:
            self._p(rel).mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# Firestore (text/JSON) + GCS (binary) backend.
# ──────────────────────────────────────────────────────────────────────────────
class FirestoreGcsBackend(StorageBackend):
    """Durable cloud persistence.

    Text/JSON  → one Firestore document per relpath (deterministic id = sha1 of
                 the relpath, so writes are idempotent upserts). Each doc carries
                 {path, parent, name, text, _updated} so listings are plain
                 equality/range queries. Firestore's 1 MiB/document limit applies;
                 the JSON blobs this app stores (progress, projects, paths) sit
                 well under it.
    Bytes      → one GCS object per relpath (object name == relpath). GCS's native
                 prefix+delimiter listing gives the file/subdir split for free.

    A single reldir may hold both (e.g. catalog inputs: binary files + .meta.json
    sidecars); list_files unions Firestore and GCS results.
    """

    def __init__(self, project: str, database: str, prefix: str, bucket_name: str):
        from google.cloud import firestore, storage  # lazy: only cloud mode needs these

        if not bucket_name:
            raise ValueError("STORAGE=cloud requires WAI_GCS_BUCKET to be set.")
        self._collection = f"{prefix}_files"
        self._db = firestore.Client(project=project or None, database=database)
        self._gcs = storage.Client(project=project or None)
        self._bucket = self._gcs.bucket(bucket_name)
        self._SERVER_TIMESTAMP = firestore.SERVER_TIMESTAMP

    # ── helpers ──
    @staticmethod
    def _norm(relpath: str) -> str:
        return relpath.strip("/")

    @staticmethod
    def _parent_of(relpath: str) -> str:
        rel = relpath.strip("/")
        return rel.rsplit("/", 1)[0] if "/" in rel else ""

    @staticmethod
    def _name_of(relpath: str) -> str:
        return relpath.strip("/").rsplit("/", 1)[-1]

    def _doc(self, relpath: str):
        doc_id = hashlib.sha1(self._norm(relpath).encode("utf-8")).hexdigest()
        return self._db.collection(self._collection).document(doc_id)

    def _blob(self, relpath: str):
        return self._bucket.blob(self._norm(relpath))

    # ── text / JSON (Firestore) ──
    def read_text(self, relpath: str) -> Optional[str]:
        snap = self._doc(relpath).get()
        return snap.to_dict().get("text") if snap.exists else None

    def write_text(self, relpath: str, text: str) -> None:
        rel = self._norm(relpath)
        self._doc(relpath).set({
            "path": rel,
            "parent": self._parent_of(rel),
            "name": self._name_of(rel),
            "text": text,
            "_updated": self._SERVER_TIMESTAMP,
        })

    # ── bytes (GCS) ──
    def read_bytes(self, relpath: str) -> Optional[bytes]:
        blob = self._blob(relpath)
        return blob.download_as_bytes() if blob.exists() else None

    def write_bytes(self, relpath: str, data: bytes) -> None:
        self._blob(relpath).upload_from_string(data)

    # ── existence / deletion (either store) ──
    def exists(self, relpath: str) -> bool:
        if self._doc(relpath).get().exists:
            return True
        return self._blob(relpath).exists()

    def delete(self, relpath: str) -> bool:
        existed = False
        doc = self._doc(relpath)
        if doc.get().exists:
            doc.delete()
            existed = True
        blob = self._blob(relpath)
        if blob.exists():
            blob.delete()
            existed = True
        return existed

    # ── listing (union of Firestore parent-query + GCS prefix listing) ──
    def _firestore_children(self, reldir: str):
        parent = self._norm(reldir)
        return self._db.collection(self._collection).where("parent", "==", parent).stream()

    def _gcs_prefix(self, reldir: str) -> str:
        parent = self._norm(reldir)
        return f"{parent}/" if parent else ""

    def list_files(self, reldir: str, suffix: Optional[str] = None) -> list[str]:
        names = {d.to_dict().get("name", "") for d in self._firestore_children(reldir)}
        prefix = self._gcs_prefix(reldir)
        for blob in self._gcs.list_blobs(self._bucket, prefix=prefix, delimiter="/"):
            names.add(blob.name[len(prefix):])
        names = {n for n in names if n and "/" not in n and (suffix is None or n.endswith(suffix))}
        return sorted(names)

    def list_files_meta(self, reldir: str, suffix: Optional[str] = None) -> list[dict]:
        meta: dict[str, dict] = {}
        for d in self._firestore_children(reldir):
            data = d.to_dict()
            name = data.get("name", "")
            ts = data.get("_updated")
            mtime = ts.timestamp() if hasattr(ts, "timestamp") else 0.0
            meta[name] = {"name": name, "size": len((data.get("text") or "").encode("utf-8")), "mtime": mtime}
        prefix = self._gcs_prefix(reldir)
        for blob in self._gcs.list_blobs(self._bucket, prefix=prefix, delimiter="/"):
            name = blob.name[len(prefix):]
            mtime = blob.updated.timestamp() if blob.updated else 0.0
            meta[name] = {"name": name, "size": blob.size or 0, "mtime": mtime}
        out = [m for n, m in meta.items() if n and "/" not in n and (suffix is None or n.endswith(suffix))]
        out.sort(key=lambda m: m["name"])
        return out

    def list_dirs(self, reldir: str) -> list[str]:
        parent = self._norm(reldir)
        prefix = f"{parent}/" if parent else ""
        dirs: set[str] = set()
        # Firestore: range-scan paths under the prefix, take the next segment.
        lo = prefix
        hi = prefix + ""
        q = (self._db.collection(self._collection)
             .where("path", ">=", lo).where("path", "<", hi))
        for d in q.stream():
            rest = d.to_dict().get("path", "")[len(prefix):]
            if "/" in rest:
                dirs.add(rest.split("/", 1)[0])
        # GCS: delimiter listing exposes subdirs as prefixes.
        it = self._gcs.list_blobs(self._bucket, prefix=prefix, delimiter="/")
        list(it)  # must consume the iterator before .prefixes is populated
        for p in it.prefixes:
            dirs.add(p[len(prefix):].rstrip("/"))
        return sorted(d for d in dirs if d)

    def delete_dir(self, reldir: str) -> None:
        parent = self._norm(reldir)
        prefix = f"{parent}/" if parent else ""
        lo, hi = prefix, prefix + ""
        # Firestore: delete the reldir doc itself and everything beneath it.
        for d in self._db.collection(self._collection).where("path", ">=", lo).where("path", "<", hi).stream():
            d.reference.delete()
        self._doc(reldir).delete()
        # GCS: delete every object under the prefix.
        for blob in self._gcs.list_blobs(self._bucket, prefix=prefix):
            blob.delete()


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────
def get_backend(base_path: Path) -> StorageBackend:
    """Return the backend selected by STORAGE (defaults to local filesystem)."""
    if settings.is_cloud_storage():
        return FirestoreGcsBackend(
            project=settings.gcp_project(),
            database=settings.firestore_database(),
            prefix=settings.firestore_prefix(),
            bucket_name=settings.gcs_bucket(),
        )
    return LocalStorageBackend(base_path)
