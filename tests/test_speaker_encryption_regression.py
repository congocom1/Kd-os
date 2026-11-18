"""Persistence tests use synthetic profiles and temporary directories only."""
import json
import stat
from types import SimpleNamespace

import pytest

from core import speaker_encryption as storage


@pytest.fixture
def key():
    return pytest.importorskip('cryptography.fernet').Fernet.generate_key()


@pytest.fixture
def profile():
    result = storage.EncryptedSpeakerProfile('SPEAKER_01', 'Private Name', [0.1, 0.2], 3,
                                             {'private': 'metadata'})
    result.created_at, result.last_seen = 123.0, 456.0
    return result


def test_roundtrip(tmp_path, key, profile):
    storage.save_profile(profile, profiles_dir=tmp_path, key=key.decode())
    path = tmp_path / 'SPEAKER_01.json'
    assert 'Private Name' not in path.read_text()
    assert 'metadata' not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert storage.load_profile(profile.speaker_id, profiles_dir=tmp_path, key=key).to_dict() == profile.to_dict()


@pytest.mark.parametrize('failure', ['wrong_key', 'tamper', 'replace', 'fsync', 'crypto', 'serialize'])
def test_failure_preserves_file(tmp_path, key, profile, monkeypatch, failure):
    storage.save_profile(profile, profiles_dir=tmp_path, key=key)
    path = tmp_path / 'SPEAKER_01.json'
    if failure == 'tamper':
        data = json.loads(path.read_text())
        data['payload'] = data['payload'][:-8] + 'abcdefgh'
        path.write_text(json.dumps(data))
    before = path.read_bytes()
    if failure == 'wrong_key':
        key = storage.Fernet.generate_key()
    elif failure in ('replace', 'fsync'):
        def fail(*args):
            raise OSError('injected write failure')
        monkeypatch.setattr(storage.os, failure, fail)
    elif failure == 'crypto':
        monkeypatch.setattr(storage, '_FERNET_AVAILABLE', False)
    elif failure == 'serialize':
        profile.metadata = {'bad': object()}
    if failure in ('wrong_key', 'tamper', 'crypto'):
        with pytest.raises(storage.ProfilePersistenceError):
            storage.load_profile(profile.speaker_id, profiles_dir=tmp_path, key=key)
    with pytest.raises((storage.ProfilePersistenceError, OSError, TypeError)):
        storage.save_profile(profile, profiles_dir=tmp_path, key=key)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_explicit_migration_only(tmp_path, key, profile):
    path = tmp_path / 'SPEAKER_01.json'
    path.write_text(json.dumps(profile.to_dict()))
    before = path.read_bytes()
    assert storage.load_profile(profile.speaker_id, profiles_dir=tmp_path,
                                allow_legacy=True).to_dict() == profile.to_dict()
    with pytest.raises(storage.ProfilePersistenceError):
        storage.save_profile(profile, profiles_dir=tmp_path, key=key)
    with pytest.raises(storage.ProfilePersistenceError):
        storage.save_profile(profile, profiles_dir=tmp_path, key=b'bad', migrate_legacy=True)
    assert path.read_bytes() == before
    storage.save_profile(profile, profiles_dir=tmp_path, key=key, migrate_legacy=True)
    assert storage.load_profile(profile.speaker_id, profiles_dir=tmp_path, key=key).to_dict() == profile.to_dict()


@pytest.mark.parametrize('embedding', [None, [1.0], 'tampered'])
def test_draft_never_swallows_decryption_failure(key, profile, embedding):
    data = profile.to_dict()
    data[storage._PROFILE_SENTINEL] = True
    data['embedding'] = embedding
    with pytest.raises(storage.ProfilePersistenceError):
        storage.EncryptedSpeakerProfile.from_dict(data, key=key, allow_legacy=True)


def test_keyring_strings_and_side_effect_free_audit(tmp_path, monkeypatch):
    pytest.importorskip('cryptography.fernet')
    backend = type('Keyring', (), {'__module__': 'keyring.backends.SecretService'})()
    values = {}
    def set_password(service, user, value):
        assert isinstance(value, str)
        values[(service, user)] = value
    fake = SimpleNamespace(get_keyring=lambda: backend,
                           get_password=lambda service, user: values.get((service, user)),
                           set_password=set_password)
    monkeypatch.setattr(storage, 'keyring', fake)
    monkeypatch.setattr(storage, '_KEYRING_AVAILABLE', True)
    monkeypatch.setattr(storage, 'PROFILES_DIR', tmp_path)
    assert not storage.get_encryption_status()['encryption_key_configured']
    assert not values
    key = storage._get_encryption_key(create=True)
    assert isinstance(key, bytes)
    assert storage._get_encryption_key() == key
    assert storage.get_encryption_status()['encryption_key_configured']
    assert not list(tmp_path.iterdir())
    fake.get_keyring = lambda: object()
    with pytest.raises(storage.ProfilePersistenceError):
        storage._get_encryption_key(create=True)


def test_no_key_no_plaintext(tmp_path, profile, monkeypatch):
    monkeypatch.setattr(storage, '_KEYRING_AVAILABLE', False)
    with pytest.raises(storage.ProfilePersistenceError):
        storage.save_profile(profile, profiles_dir=tmp_path)
    with pytest.raises(storage.ProfilePersistenceError):
        storage.save_legacy_profile(profile, tmp_path / 'legacy.json')
    assert not list(tmp_path.iterdir())


def test_invalid_id_and_mismatched_ciphertext(tmp_path, key, profile):
    with pytest.raises(storage.ProfilePersistenceError):
        storage.load_profile('../escape', profiles_dir=tmp_path, key=key)
    storage.save_profile(profile, profiles_dir=tmp_path, key=key)
    (tmp_path / 'OTHER.json').write_bytes((tmp_path / 'SPEAKER_01.json').read_bytes())
    with pytest.raises(storage.ProfilePersistenceError):
        storage.load_profile('OTHER', profiles_dir=tmp_path, key=key)


def test_processor_integration(tmp_path, key, profile):
    pytest.importorskip('numpy')
    from core.multi_person_voice import MultiPersonVoiceProcessor, SpeakerProfile
    processor = MultiPersonVoiceProcessor(profiles_dir=tmp_path, encryption_key=key)
    processor._save_profile(SpeakerProfile.from_dict(profile.to_dict()))
    processor._load_profiles()
    loaded = processor.get_profile(profile.speaker_id)
    assert loaded.name == profile.name
    assert loaded.created_at == profile.created_at
    assert loaded.embedding.tolist() == pytest.approx(profile.embedding)
    path = tmp_path / 'SPEAKER_01.json'
    path.write_text(json.dumps(profile.to_dict()))
    before = path.read_bytes()
    processor._load_profiles()
    with pytest.raises(storage.ProfilePersistenceError):
        processor._save_profile(loaded)
    assert path.read_bytes() == before


def test_valid_draft_and_missing_crypto(tmp_path, key, profile, monkeypatch):
    data = profile.to_dict()
    data[storage._PROFILE_SENTINEL] = True
    data['embedding'] = storage.Fernet(key).encrypt(json.dumps(profile.embedding).encode()).decode()
    assert storage.EncryptedSpeakerProfile.from_dict(data, key=key).to_dict() == profile.to_dict()
    monkeypatch.setattr(storage, '_FERNET_AVAILABLE', False)
    with pytest.raises(storage.ProfilePersistenceError):
        storage.save_profile(profile, profiles_dir=tmp_path, key=key)
    assert not list(tmp_path.iterdir())


def test_processor_tampered_file_not_overwritten(tmp_path, key, profile):
    pytest.importorskip('numpy')
    from core.multi_person_voice import MultiPersonVoiceProcessor, SpeakerProfile
    path = tmp_path / 'SPEAKER_01.json'
    path.write_text('{broken')
    processor = MultiPersonVoiceProcessor(profiles_dir=tmp_path, encryption_key=key)
    processor._load_profiles()
    assert processor.get_profile(profile.speaker_id) is None
    with pytest.raises(storage.ProfilePersistenceError):
        processor._save_profile(SpeakerProfile.from_dict(profile.to_dict()))
    assert path.read_text() == '{broken'
