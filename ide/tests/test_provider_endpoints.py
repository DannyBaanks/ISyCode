"""How a provider turns `endpoint` into the URL it actually calls.

This is the contract nobody wrote down, and its absence produced a real 404:
`config.yaml` stored the NVIDIA endpoint already carrying `/chat/completions`,
`openai.py` appended it again, and every message went to

    https://integrate.api.nvidia.com/v1/chat/completions/chat/completions

which answers 404. The UI showed no error, so the symptom was silence.

None of the existing provider tests caught it because none of them ever look at
the URL that leaves the process. These do.
"""
from __future__ import annotations

import unittest

from core.agent.providers.base import ProviderConfig


def _config(endpoint: str) -> ProviderConfig:
    return ProviderConfig(name="t", provider_type="nvidia",
                          model="m", endpoint=endpoint)


class UrlForTests(unittest.TestCase):
    """`endpoint` may legitimately arrive in either shape, so both must work."""

    BASE = "https://integrate.api.nvidia.com/v1"
    PATH = "/chat/completions"
    WANT = "https://integrate.api.nvidia.com/v1/chat/completions"

    def test_base_url_gets_the_path_appended(self):
        self.assertEqual(_config(self.BASE).url_for(self.PATH), self.WANT)

    def test_trailing_slash_does_not_double_up(self):
        self.assertEqual(_config(self.BASE + "/").url_for(self.PATH), self.WANT)

    def test_an_endpoint_that_already_has_the_path_is_left_alone(self):
        """The regression. This is exactly what config.yaml contained."""
        self.assertEqual(_config(self.WANT).url_for(self.PATH), self.WANT)

    def test_already_complete_with_trailing_slash(self):
        self.assertEqual(_config(self.WANT + "/").url_for(self.PATH), self.WANT)

    def test_path_without_a_leading_slash_is_accepted(self):
        self.assertEqual(_config(self.BASE).url_for("chat/completions"), self.WANT)

    def test_a_different_path_is_still_appended(self):
        self.assertEqual(_config(self.BASE).url_for("/models"),
                         "https://integrate.api.nvidia.com/v1/models")

    def test_a_path_appearing_mid_url_is_not_mistaken_for_the_suffix(self):
        """`/v1` inside a host or prefix must not confuse the check."""
        cfg = _config("https://gw.example.com/chat/completions/v1")
        self.assertEqual(cfg.url_for("/chat/completions"),
                         "https://gw.example.com/chat/completions/v1/chat/completions")

    def test_empty_endpoint_raises_rather_than_calling_a_bare_path(self):
        """Silently posting to "/chat/completions" is how you get a confusing
        error far from the cause."""
        with self.assertRaises(ValueError):
            _config("").url_for(self.PATH)


class SuffixStrippingTests(unittest.TestCase):
    """`anthropic.py` uses rstrip("/v1"), which does not strip a suffix.

    str.rstrip takes a *set of characters*: it removes any trailing '/', 'v' or
    '1'. It happens to give the right answer for ".../v1" and the wrong one for
    anything ending in those characters.
    """

    def test_rstrip_of_a_suffix_is_not_suffix_removal(self):
        self.assertEqual("https://api.example.com/v1".rstrip("/v1"),
                         "https://api.example.com")
        # The same call mangles a host that merely ends in a stripped character.
        self.assertEqual("https://api.example.com/v11".rstrip("/v1"),
                         "https://api.example.com")
        self.assertEqual("https://ollama.local/v".rstrip("/v1"),
                         "https://ollama.local")

    def test_base_url_helper_removes_the_suffix_properly(self):
        cfg = _config("https://api.anthropic.com/v1")
        self.assertEqual(cfg.base_url(), "https://api.anthropic.com")

    def test_base_url_leaves_a_host_ending_in_v_alone(self):
        cfg = _config("https://api.example.com/srv")
        self.assertEqual(cfg.base_url(), "https://api.example.com/srv")


if __name__ == "__main__":
    unittest.main()
