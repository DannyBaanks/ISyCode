import asyncio, sys, json
from pathlib import Path
from isycode.headless import _register_saved_key_reader
from isycode.providers import Provider, load_provider_key
import isycode.provider_errors as pe
_register_saved_key_reader(Path(sys.argv[1]).resolve())
captured = {}
real = pe.error_signals
def spy(body, headers=None):
    raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    captured["body"] = raw[:1500]
    return real(body, headers)
pe.error_signals = spy
from isycode.chat_transport import provider_complete
p = Provider(name="nvidia", model="openai/gpt-oss-20b", api_key=load_provider_key("nvidia") or None)
msg = [{"role": "user", "content": ("The parser module tokenizes input. " * 26000)}]
try:
    asyncio.run(provider_complete(p, msg, max_tokens=16))
    print("ACCEPTED")
except Exception as exc:
    print(type(exc).__name__, getattr(exc, "status", None), getattr(exc, "provider_code", None))
print(json.dumps(captured, ensure_ascii=False))
