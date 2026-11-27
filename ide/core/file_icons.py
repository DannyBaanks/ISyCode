"""Shared file identities: SVG keys for Qt and font-independent ASCII for TUI."""
from pathlib import PurePosixPath

# Asset key, ASCII marker. No Qt import or filesystem/network access here.
TYPES = {
    "py": ("python", "PY"), "pyi": ("python", "PY"), "pyw": ("python", "PY"),
    "js": ("js", "JS"), "mjs": ("js", "JS"), "cjs": ("js", "JS"),
    "ts": ("typescript", "TS"), "jsx": ("reactjs", "JSX"), "tsx": ("reactts", "TSX"),
    "md": ("markdown", "MD"), "markdown": ("markdown", "MD"),
    "json": ("json", "JSON"), "jsonc": ("json", "JSON"),
    "yml": ("yaml", "YAML"), "yaml": ("yaml", "YAML"),
    "html": ("html", "HTML"), "htm": ("html", "HTML"),
    "css": ("css", "CSS"), "rs": ("rust", "RS"), "go": ("go", "GO"),
    "c": ("c", "C"), "h": ("c", "C"), "cpp": ("cpp", "CPP"),
    "hpp": ("cpp", "CPP"), "cc": ("cpp", "CPP"), "java": ("java", "JAVA"),
    "sh": ("shell", "SH"), "bash": ("shell", "SH"), "toml": ("toml", "TOML"),
    **{ext: ("image", "IMG") for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "ico")},
}
NAMES = {"dockerfile": ("docker", "DOCKER"), ".gitignore": ("git", "GIT"),
         ".gitattributes": ("git", "GIT"), ".gitmodules": ("git", "GIT")}


def file_identity(path: str, is_dir: bool = False) -> tuple[str, str]:
    if is_dir:
        return "default_folder", "[DIR]"
    name = PurePosixPath(str(path).replace("\\", "/")).name.lower()
    key, marker = NAMES.get(name, TYPES.get(name.rsplit(".", 1)[-1] if "." in name else "", ("default_file", "FILE")))
    return (key if key.startswith("default_") else "file_type_" + key), "[" + marker + "]"


def ascii_file_label(path: str, is_dir: bool = False) -> str:
    return file_identity(path, is_dir)[1] + " " + str(path)
