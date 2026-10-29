"""Policy for workspace paths that may hold credentials (Audit 2026-10-09, F4)."""
import pytest

from isycode import sensitive_paths
from isycode.sensitive_paths import is_sensitive_path_name


@pytest.mark.parametrize("name", [
    # Names the policy has always masked.
    ".git", ".isycode", ".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", "credentials",
    # Common credential containers added by the 2026-10-09 audit.
    ".git-credentials", ".htpasswd", ".pgpass",
    "id_dsa", "id_ecdsa", "credentials.json",
    "secrets.json", "secrets.yaml", "secrets.yml", "vault.json",
    # Env files and key containers by suffix.
    ".env", ".env.local", ".env.production",
    "server.pem", "server.key", "bundle.p12", "bundle.pfx",
    "terraform.tfstate", "app.jks", "app.keystore",
])
def test_credential_containers_are_masked(name):
    assert is_sensitive_path_name(name) is True


@pytest.mark.parametrize("name", [
    # Ordinary project files. Masking these would hide them from the sandbox
    # without a security gain, so the policy stays deliberately narrow.
    "config.json", "docker-compose.yml", "prod.env", "token", "api_token.txt",
    "password.txt", "README.md", "main.py", "Dockerfile", "package.json",
])
def test_ordinary_project_files_are_not_masked(name):
    assert is_sensitive_path_name(name) is False


def test_matching_ignores_case_and_a_trailing_variant_is_not_a_prefix_escape():
    assert is_sensitive_path_name("ID_RSA") is True
    assert is_sensitive_path_name(".GIT-CREDENTIALS") is True
    assert is_sensitive_path_name("SERVER.PEM") is True
    # ".envrc" is not an env secret file; only ".env" and ".env.*" are.
    assert is_sensitive_path_name(".envrc") is False


def test_the_policy_is_the_single_shared_classifier():
    """Both modules the boundary relies on must read the same list."""
    from isycode.action_runtime import WorkspaceReadSystembility

    assert WorkspaceReadSystembility.is_sensitive_name("credentials.json") is True
    assert WorkspaceReadSystembility.is_sensitive_name("id_dsa") is True
    assert sensitive_paths.is_sensitive_path_name("config.json") is False
