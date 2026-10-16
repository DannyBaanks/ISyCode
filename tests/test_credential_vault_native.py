"""Native vault metadata privacy without real provider credentials."""
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from isycode.credentials import CredentialVault,CredentialVaultError
from isycode.platform_storage import storage


@pytest.fixture
def fake_keyring(monkeypatch):
    import keyring
    class MemoryKeyring:
        priority=1
        def __init__(self):self.values={}
        def set_password(self,service,name,value):self.values[(service,name)]=value
        def get_password(self,service,name):return self.values.get((service,name))
        def delete_password(self,service,name):self.values.pop((service,name),None)
    backend=MemoryKeyring()
    monkeypatch.setattr(keyring,'get_keyring',lambda:backend)
    return backend


def test_vault_uses_the_shared_native_state_root(tmp_path,monkeypatch):
    from isycode.credentials import _vault_path
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'private-state'))
    assert _vault_path()==tmp_path/'private-state'/'credentials.sqlite3'


def test_vault_metadata_is_private_and_does_not_store_secret(tmp_path,fake_keyring):
    folder=tmp_path/'vault'
    vault=CredentialVault(folder/'credentials.sqlite3')
    key=vault.add('test label','parity-test','synthetic acceptance','seeded-not-a-real-key')
    assert storage.private(folder) and storage.private(vault.path)
    assert b'seeded-not-a-real-key' not in vault.path.read_bytes()
    assert vault.list_metadata()[0]['id']==key
    assert vault.revoke(key)


def test_vault_refuses_unsafe_existing_metadata(tmp_path,fake_keyring):
    folder=tmp_path/'vault';storage.ensure_directory(folder)
    path=folder/'credentials.sqlite3';path.write_bytes(b'untrusted-existing')
    if os.name=='nt':
        import win32security as s
        d=s.ConvertStringSecurityDescriptorToSecurityDescriptor('D:P(A;;FA;;;WD)',1)
        s.SetNamedSecurityInfo(str(path),s.SE_FILE_OBJECT, s.DACL_SECURITY_INFORMATION|s.PROTECTED_DACL_SECURITY_INFORMATION,None,None,d.GetSecurityDescriptorDacl(),None)
    else:path.chmod(0o666)
    before=path.read_bytes()
    try:
        with pytest.raises((CredentialVaultError,ValueError),match='private|unsafe'):
            CredentialVault(path)
        assert path.read_bytes()==before
    finally:path.unlink(missing_ok=True)


def test_real_windows_keyring_synthetic_roundtrip(tmp_path):
    if os.name!='nt':pytest.skip('native Windows keyring witness')
    import secrets
    try:vault=CredentialVault(tmp_path/'live-vault'/'credentials.sqlite3')
    except CredentialVaultError as exc:pytest.skip('NOT_DEMONSTRATED: secure OS keyring unavailable: '+str(exc))
    seed='synthetic-parity-'+secrets.token_hex(16)
    key=None
    try:
        key=vault.add('Windows parity control','parity-control','synthetic acceptance',seed)
        assert vault._keyring.get_password('isycode.api-key',key)==seed
        assert seed.encode() not in vault.path.read_bytes()
    finally:
        if key is not None:assert vault.revoke(key)
