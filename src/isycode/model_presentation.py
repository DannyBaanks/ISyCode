"""Readable model names for compact UI labels; transport IDs stay untouched."""
import re


def model_display_name(model_id: str) -> str:
    name = model_id.rsplit("/", 1)[-1]
    words = re.split(r"[-_]+", name)
    brands = {"glm": "GLM", "gpt": "GPT", "llama": "Llama", "qwen": "Qwen",
              "deepseek": "DeepSeek", "kimi": "Kimi", "nemotron": "Nemotron"}
    return " ".join(brands.get(word.lower(), word.capitalize() if word.isalpha() else word)
                    for word in words)
