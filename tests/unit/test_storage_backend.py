"""Unit tests for the pluggable storage backend.

The LocalStorageBackend is exercised directly here (the whole integration suite
also exercises it indirectly through DepartmentScopedStore). The cloud backend's
pure helpers + the factory wiring are tested without needing GCP credentials.
"""

import pytest

from src.core.storage_backend import (
    FirestoreGcsBackend,
    LocalStorageBackend,
    StorageBackend,
    get_backend,
)


def test_local_backend_text_roundtrip(tmp_path):
    io = LocalStorageBackend(tmp_path)
    assert io.read_text("a/b/c.json") is None
    io.write_text("a/b/c.json", '{"x": 1}')
    assert io.read_text("a/b/c.json") == '{"x": 1}'
    assert io.exists("a/b/c.json") is True
    assert io.delete("a/b/c.json") is True
    assert io.delete("a/b/c.json") is False  # already gone
    assert io.exists("a/b/c.json") is False


def test_local_backend_bytes_roundtrip(tmp_path):
    io = LocalStorageBackend(tmp_path)
    io.write_bytes("raw/pic.png", b"\x89PNG\x00\x01")
    assert io.read_bytes("raw/pic.png") == b"\x89PNG\x00\x01"
    assert io.read_bytes("raw/missing.png") is None


def test_local_backend_list_files_and_dirs(tmp_path):
    io = LocalStorageBackend(tmp_path)
    io.write_text("d/one.json", "1")
    io.write_text("d/two.json", "2")
    io.write_text("d/note.txt", "t")
    io.write_text("d/sub/three.json", "3")
    assert io.list_files("d", ".json") == ["one.json", "two.json"]
    assert io.list_files("d") == ["note.txt", "one.json", "two.json"]
    assert io.list_dirs("d") == ["sub"]
    assert io.list_files("does/not/exist") == []


def test_local_backend_list_files_meta_has_size_and_mtime(tmp_path):
    io = LocalStorageBackend(tmp_path)
    io.write_text("d/a.json", "hello")
    meta = io.list_files_meta("d", ".json")
    assert len(meta) == 1
    assert meta[0]["name"] == "a.json"
    assert meta[0]["size"] == 5
    assert isinstance(meta[0]["mtime"], float)


def test_local_backend_delete_dir(tmp_path):
    io = LocalStorageBackend(tmp_path)
    io.write_text("bundle/v1/raw.json", "1")
    io.write_text("bundle/v1/meta.json", "m")
    io.delete_dir("bundle/v1")
    assert io.list_files("bundle/v1") == []
    assert io.exists("bundle/v1/raw.json") is False


def test_get_backend_defaults_to_local(tmp_path, monkeypatch):
    monkeypatch.delenv("STORAGE", raising=False)
    backend = get_backend(tmp_path)
    assert isinstance(backend, LocalStorageBackend)
    assert isinstance(backend, StorageBackend)


def test_get_backend_cloud_requires_bucket(tmp_path, monkeypatch):
    # STORAGE=cloud with no WAI_GCS_BUCKET fails fast, before any GCP client is
    # constructed — so this is safe to assert without credentials.
    monkeypatch.setenv("STORAGE", "cloud")
    monkeypatch.delenv("WAI_GCS_BUCKET", raising=False)
    with pytest.raises(ValueError, match="WAI_GCS_BUCKET"):
        get_backend(tmp_path)


@pytest.mark.parametrize(
    "relpath,parent,name",
    [
        ("user_progress/operations/emp_001.json", "user_progress/operations", "emp_001.json"),
        ("kpi_store/operations_daily_2026-01-01.json", "kpi_store", "operations_daily_2026-01-01.json"),
        ("top.json", "", "top.json"),
        ("/leading/slash.json", "leading", "slash.json"),
    ],
)
def test_cloud_backend_path_helpers(relpath, parent, name):
    # Pure static helpers — the Firestore listing/keying depends on these being
    # correct, so pin them even though the live backend needs GCP to instantiate.
    assert FirestoreGcsBackend._parent_of(relpath) == parent
    assert FirestoreGcsBackend._name_of(relpath) == name
    assert FirestoreGcsBackend._norm("/a/b/") == "a/b"
