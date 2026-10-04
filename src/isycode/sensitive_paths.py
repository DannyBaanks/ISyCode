"""Shared filename policy for workspace paths that may contain credentials."""

SENSITIVE_NAMES = frozenset({
    ".git", ".isycode", ".ssh", ".aws", ".gnupg",
    ".netrc", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", "credentials", "secrets.json",
})
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def is_sensitive_path_name(name: str) -> bool:
    lower = name.casefold()
    return (lower in SENSITIVE_NAMES
            or lower == ".env" or lower.startswith(".env.")
            or lower.endswith(SENSITIVE_SUFFIXES))
