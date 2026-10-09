"""Shared filename policy for workspace paths that may contain credentials."""

SENSITIVE_NAMES = frozenset({
    ".git", ".isycode", ".ssh", ".aws", ".gnupg",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd", ".pgpass",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "credentials.json",
    "secrets.json", "secrets.yaml", "secrets.yml", "vault.json",
})
# Suffixes that name a credential container regardless of its base name. The
# list stays conservative on purpose: generic stems ("config.json", "token",
# "prod.env") are left out, because masking every plausible name would hide
# ordinary project files from the sandbox without a real security gain. That
# limitation is deliberate and recorded in the audit of 2026-10-09.
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".tfstate", ".jks", ".keystore")


def is_sensitive_path_name(name: str) -> bool:
    lower = name.casefold()
    return (lower in SENSITIVE_NAMES
            or lower == ".env" or lower.startswith(".env.")
            or lower.endswith(SENSITIVE_SUFFIXES))
