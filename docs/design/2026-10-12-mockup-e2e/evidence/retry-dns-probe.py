"""Negative/control probe: does the fake retry transport still resolve DNS?"""
import json
import sys

import pytest

mode = sys.argv.pop(1)
calls = []


class ResolverProbe:
    @pytest.fixture(autouse=True)
    def resolver(self, monkeypatch):
        from isycode import egress

        def controlled_ips(host, port):
            calls.append({"host": host, "port": port, "mode": mode})
            if mode == "deny":
                raise egress.EgressDenied("isolated negative DNS probe")
            return ("93.184.216.34",)

        monkeypatch.setattr(egress, "_ips", controlled_ips)


result = pytest.main([
    "-q", "tests/test_turn_control.py::test_g6_04_retry_keeps_the_new_draft_and_transcript_order",
    "--tb=short", "-p", "no:cacheprovider"], plugins=[ResolverProbe()])
print(json.dumps({"mode": mode, "resolver_calls": calls, "exit": int(result)}))
raise SystemExit(result)
