"""Featured models come from the live catalog; nothing is invented."""
from isycode.providers import featured_models


def test_featured_models_match_real_catalog_ids_only():
    catalog = ["meta/llama-3.1-8b-instruct", "zai-org/glm-5.3", "zai-org/glm-5.3-flash",
               "moonshotai/kimi-k3-instruct", "deepseek-ai/deepseek-v4.1-flash",
               "deepseek-ai/deepseek-v4"]
    assert featured_models(catalog) == [
        ("GLM 5.3 Flash", "zai-org/glm-5.3-flash"),
        ("GLM 5.3", "zai-org/glm-5.3"),
        ("Kimi K3", "moonshotai/kimi-k3-instruct"),
        # The exact NVIDIA ID given by Danny.
        ("DeepSeek V4.1 Flash", "deepseek-ai/deepseek-v4.1-flash"),
    ]


def test_missing_featured_models_are_reported_not_guessed():
    assert featured_models(["meta/llama-3.1-8b-instruct"]) == [
        ("GLM 5.3 Flash", None), ("GLM 5.3", None), ("Kimi K3", None),
        ("DeepSeek V4.1 Flash", None)]


def test_similar_but_different_versions_do_not_match():
    assert featured_models(["zai-org/glm-5.30", "zai-org/glm-5.31-flash",
                            "moonshotai/kimi-k2-instruct", "moonshotai/kimi-k30",
                            "deepseek-ai/deepseek-v4.10-flash"]) == [
        ("GLM 5.3 Flash", None), ("GLM 5.3", None), ("Kimi K3", None),
        ("DeepSeek V4.1 Flash", None)]
