"""Unit tests for credential loading + bcrypt password verification."""

import json

from src.core import auth_store


def test_hash_and_verify_roundtrip():
    h = auth_store.hash_password("s3cret")
    account = {"password_hash": h}
    assert auth_store.verify_password(account, "s3cret") is True
    assert auth_store.verify_password(account, "wrong") is False


def test_verify_rejects_empty_account():
    assert auth_store.verify_password({}, "anything") is False
    assert auth_store.verify_password(None, "anything") is False


def test_legacy_plaintext_still_verifies():
    # An un-migrated file with a plaintext `password` field must keep working.
    account = {"password": "plainpw"}
    assert auth_store.verify_password(account, "plainpw") is True
    assert auth_store.verify_password(account, "nope") is False


def test_env_credentials_take_precedence(monkeypatch):
    blob = {"alice": {"password_hash": auth_store.hash_password("pw"),
                      "display_name": "Alice", "job_level": "manager", "manager_id": ""}}
    monkeypatch.setenv("WAI_CREDENTIALS_JSON", json.dumps(blob))
    account = auth_store.get_account("alice")
    assert account is not None
    assert auth_store.verify_password(account, "pw") is True
    # A user only present in the on-disk file is invisible when env creds are set.
    assert auth_store.get_account("manager") is None


def test_malformed_env_credentials_yield_empty(monkeypatch):
    monkeypatch.setenv("WAI_CREDENTIALS_JSON", "{not valid json")
    assert auth_store.load_credentials() == {}


def test_public_entry_never_leaks_password(monkeypatch):
    blob = {"bob": {"password_hash": "xxx", "display_name": "Bob",
                    "job_level": "individual_contributor", "manager_id": "manager"}}
    monkeypatch.setenv("WAI_CREDENTIALS_JSON", json.dumps(blob))
    entry = auth_store.public_entry("bob")
    assert entry == {"user_id": "bob", "display_name": "Bob", "role": "individual_contributor"}
    assert "password" not in entry
    assert "password_hash" not in entry
    assert auth_store.public_entry("ghost") is None
