"""Readable model names for compact UI labels; transport IDs stay untouched."""
import re

_BRANDS = {"glm": "GLM", "gpt": "GPT", "llama": "Llama", "qwen": "Qwen",
           "deepseek": "DeepSeek", "kimi": "Kimi", "nemotron": "Nemotron"}

OTHER_FAMILY = "Otros"


def model_display_name(model_id: str) -> str:
    name = model_id.rsplit("/", 1)[-1]
    words = re.split(r"[-_]+", name)
    return " ".join(_BRANDS.get(word.lower(), word.capitalize() if word.isalpha() else word)
                    for word in words)


def model_family(model_id: str) -> str:
    """Brand-level family of one model id for grouped pickers.

    The family is the first recognized brand of the id's last path segment,
    matched as a token ("glm-5.3" -> GLM) or as a brand prefix with a digit
    boundary ("qwen3-coder" -> Qwen). Unrecognized ids land in Otros.
    """
    name = model_id.rsplit("/", 1)[-1]
    first = re.split(r"[-_]+", name, maxsplit=1)[0].lower()
    if first in _BRANDS:
        return _BRANDS[first]
    prefixed = [label for key, label in _BRANDS.items()
                if first.startswith(key) and (first[len(key):] or "").isdigit()]
    return prefixed[0] if len(prefixed) == 1 else OTHER_FAMILY
