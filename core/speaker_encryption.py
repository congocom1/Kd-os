"""Fail-closed encrypted persistence. Legacy reads never migrate data.

Keys are supplied explicitly or held in a supported OS keyring, never files.
Only explicit per-profile migration may replace legacy plaintext.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet
    _FERNET_AVAILABLE = True
except ImportError:  # pragma: no cover
    Fernet = None
    _FERNET_AVAILABLE = False
try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    keyring = None
    _KEYRING_AVAILABLE = False

_PROFILE_SENTINEL = "__kd_speaker_profile_v1__"
_ENVELOPE = "__kd_speaker_profile_v2__"
PROFILES_DIR = Path(__file__).resolve().parent.parent / "memory" / "speakers"
_legacy_profiles_dir: Path | None = None


class ProfilePersistenceError(RuntimeError):
    """Storage unavailable or profile authentication failed."""


def _get_encryption_key(*, create: bool = False) -> bytes:
    if not _FERNET_AVAILABLE or not _KEYRING_AVAILABLE:
        raise ProfilePersistenceError("OS keyring and cryptography or explicit key required")
    try:
        # Reject plaintext/null backends and chains with ambiguous destinations.
        backend = keyring.get_keyring()
        if type(backend).__module__ not in {
            "keyring.backends.SecretService", "keyring.backends.macOS",
            "keyring.backends.Windows", "keyring.backends.kwallet",
        }:
            raise ValueError("Unsupported keyring backend")
        value = keyring.get_password("kd_speaker_profiles", "encryption_key")
        if value is None and create:
            value = Fernet.generate_key().decode("ascii")
            keyring.set_password("kd_speaker_profiles", "encryption_key", value)
            if keyring.get_password("kd_speaker_profiles", "encryption_key") != value:
                raise ValueError("Keyring did not retain key")
        if not isinstance(value, str):
            raise ValueError("No key configured")
        result = value.encode("ascii")
        Fernet(result)
        return result
    except Exception:
        raise ProfilePersistenceError("Valid key unavailable from supported OS keyring") from None


def _get_fernet(key: bytes | str | None = None, *, create: bool = False):
    if not _FERNET_AVAILABLE:
        raise ProfilePersistenceError("cryptography is required")
    try:
        if key is None:
            key = _get_encryption_key(create=create)
        if isinstance(key, str):
            key = key.encode("ascii")
        return Fernet(key)
    except Exception:
        raise ProfilePersistenceError("Speaker encryption key unavailable or invalid") from None


def profile_path(speaker_id: str, profiles_dir: Path | None = None) -> Path:
    if not isinstance(speaker_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", speaker_id):
        raise ProfilePersistenceError("Invalid speaker ID")
    return Path(PROFILES_DIR if profiles_dir is None else profiles_dir) / f"{speaker_id}.json"


class EncryptedSpeakerProfile:
    """In-memory profile; to_dict is not a persistence API."""

    def __init__(self, speaker_id: str, name: str | None = None,
                 embedding: list[float] | None = None, sample_count: int = 0,
                 metadata: dict | None = None):
        self.speaker_id = speaker_id
        self.name = name
        self.embedding = embedding
        self.sample_count = sample_count
        self.metadata = {} if metadata is None else metadata
        self.created_at = time.time()
        self.last_seen = self.created_at

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in (
            "speaker_id", "name", "embedding", "sample_count", "metadata",
            "created_at", "last_seen")}

    @classmethod
    def from_dict(cls, data: dict, *, key: bytes | str | None = None,
                  allow_legacy: bool = False) -> "EncryptedSpeakerProfile":
        try:
            if not isinstance(data, dict):
                raise ValueError("Invalid document")
            if _ENVELOPE in data:
                if data[_ENVELOPE] is not True or set(data) != {_ENVELOPE, "payload"}:
                    raise ValueError("Invalid envelope")
                data = json.loads(_get_fernet(key).decrypt(data["payload"].encode("ascii")))
            elif _PROFILE_SENTINEL in data:
                # Draft v1 authenticated only embeddings. Reject its plaintext
                # fallback and missing embeddings rather than returning None.
                if data[_PROFILE_SENTINEL] is not True:
                    raise ValueError("Invalid sentinel")
                data = dict(data)
                data["embedding"] = json.loads(
                    _get_fernet(key).decrypt(data["embedding"].encode("ascii")))
            elif not allow_legacy:
                raise ValueError("Explicit legacy read required")
            profile_path(data["speaker_id"])
            embedding = data.get("embedding")
            if embedding is not None:
                if not isinstance(embedding, list):
                    raise ValueError("Invalid embedding")
                embedding = [float(x) for x in embedding]
            profile = cls(data["speaker_id"], data.get("name"), embedding,
                          data.get("sample_count", 0), data.get("metadata", {}))
            profile.created_at = data.get("created_at", profile.created_at)
            profile.last_seen = data.get("last_seen", profile.last_seen)
            return profile
        except Exception:
            raise ProfilePersistenceError("Profile is invalid or cannot be decrypted") from None


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".speaker-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def save_profile(profile: EncryptedSpeakerProfile, *, profiles_dir: Path | None = None,
                 key: bytes | str | None = None, migrate_legacy: bool = False) -> None:
    """Encrypt then replace. Existing ciphertext must authenticate first."""
    path = profile_path(profile.speaker_id, profiles_dir)
    if path.is_symlink():
        raise ProfilePersistenceError("Refusing symlink destination")
    exists = path.exists()
    if exists:
        previous = load_profile(profile.speaker_id, profiles_dir=profiles_dir,
                                key=key, allow_legacy=migrate_legacy)
        if previous is None:
            raise ProfilePersistenceError("Profile disappeared during save")
    fernet = _get_fernet(key, create=not exists)
    payload = fernet.encrypt(json.dumps(profile.to_dict(), allow_nan=False).encode("utf-8"))
    content = json.dumps({_ENVELOPE: True, "payload": payload.decode("ascii")}).encode("utf-8")
    _atomic_write(path, content)


def load_profile(speaker_id: str, *, profiles_dir: Path | None = None,
                 key: bytes | str | None = None,
                 allow_legacy: bool = False) -> EncryptedSpeakerProfile | None:
    path = profile_path(speaker_id, profiles_dir)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        profile = EncryptedSpeakerProfile.from_dict(json.loads(content), key=key,
                                                    allow_legacy=allow_legacy)
        if profile.speaker_id != speaker_id:
            raise ValueError("Mismatched speaker ID")
        return profile
    except Exception:
        raise ProfilePersistenceError("Profile is invalid or cannot be decrypted") from None


def delete_profile(speaker_id: str, *, profiles_dir: Path | None = None) -> bool:
    path = profile_path(speaker_id, profiles_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def set_legacy_profiles_dir(path: Path) -> None:
    global _legacy_profiles_dir
    _legacy_profiles_dir = Path(path)


def load_legacy_profile(speaker_id: str) -> EncryptedSpeakerProfile | None:
    if _legacy_profiles_dir is None:
        return None
    return load_profile(speaker_id, profiles_dir=_legacy_profiles_dir, allow_legacy=True)


def save_legacy_profile(profile: EncryptedSpeakerProfile, path: Path) -> None:
    raise ProfilePersistenceError("Plaintext speaker profile writes are disabled")


def is_encryption_available() -> bool:
    """Implementation availability, not key readiness."""
    return _FERNET_AVAILABLE


def get_encryption_status() -> dict[str, Any]:
    try:
        _get_fernet()
        configured = True
    except Exception:
        configured = False
    return {"fernet_available": _FERNET_AVAILABLE,
            "keyring_available": _KEYRING_AVAILABLE,
            "encryption_key_configured": configured,
            "profiles_encrypted": _profiles_encrypted_count()}


def _profiles_encrypted_count() -> int:
    count = 0
    for path in PROFILES_DIR.glob("*.json"):
        try:
            if load_profile(path.stem) is not None:
                count += 1
        except Exception:
            pass
    return count
