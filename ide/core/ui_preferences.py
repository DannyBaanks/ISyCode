"""Small public UI preferences; no credentials or execution permissions."""

import json

from core.ide_state import atomic_write, state_home, state_lock


class UiPreferences:
    defaults = {
        "view": "conversation",
        "editor_font_size": 12,
        "remember_view": True,
        "last_workspace": "",
        "github_auto_verify": None,
    }

    def __init__(self):
        self.path = state_home() / "appearance.json"

    def load(self):
        values = dict(self.defaults)
        if not self.path.exists():
            return values
        if self.path.is_symlink() or self.path.stat().st_size > 8192:
            raise ValueError("Preferencias de interfaz no válidas.")
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Preferencias de interfaz no válidas.")
        if data.get("view") in {"conversation", "code"}:
            values["view"] = data["view"]
        if isinstance(data.get("editor_font_size"), int) and 9 <= data["editor_font_size"] <= 24:
            values["editor_font_size"] = data["editor_font_size"]
        if isinstance(data.get("remember_view"), bool):
            values["remember_view"] = data["remember_view"]
        if isinstance(data.get("last_workspace"), str):
            values["last_workspace"] = data["last_workspace"]
        if "github_auto_verify" in data and data["github_auto_verify"] in {None, True, False}:
            values["github_auto_verify"] = data["github_auto_verify"]
        return values

    def save(self, **updates):
        with state_lock(self.path.with_suffix(".lock")):
            data = self.load()
            for key, value in updates.items():
                if key not in self.defaults:
                    raise ValueError("Preferencia desconocida.")
                if key == "view" and value not in {"conversation", "code"}:
                    raise ValueError("Vista no válida.")
                if key == "editor_font_size" and (type(value) is not int or not 9 <= value <= 24):
                    raise ValueError("Tamaño de fuente no válido.")
                if key == "remember_view" and type(value) is not bool:
                    raise ValueError("Preferencia no válida.")
                if key == "last_workspace" and not isinstance(value, str):
                    raise ValueError("Ruta de proyecto no válida.")
                if key == "github_auto_verify" and value not in {None, True, False}:
                    raise ValueError("Preferencia de GitHub no válida.")
                data[key] = value
            atomic_write(self.path, json.dumps(data, indent=2) + "\n")
            return data
