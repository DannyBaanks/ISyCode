"""Manual smoke check against the real NVIDIA endpoint.

Renamed out of `test_*.py`: pytest collected it, found an `async def test()`
with no asyncio plugin installed, and reported a failure without ever running
it. The one check that would have caught the duplicated-URL 404 was the one
pytest silently discarded.

Run it deliberately:  python tools_check_nvidia.py
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from ui.app import AppController
import tempfile

tmp = tempfile.mkdtemp()
c = AppController(tmp)

# Test NVIDIA provider with actual API key
try:
    provider = c.provider_registry.get('NVIDIA')
    print('Provider:', type(provider).__name__)
    print('Model:', provider.config.model)
    print('Endpoint:', provider.config.endpoint)
    print('Has key:', c.has_key('NVIDIA'))
    
    # Try a simple completion
    import asyncio
    async def test():
        response = await provider.complete([{"role": "user", "content": "Say hello in 5 words"}])
        print('Response:', response.content[:100] if response.content else 'None')
        print('Tool calls:', response.tool_calls)
    
    asyncio.run(test())
    print('SUCCESS: Provider works!')
except Exception as e:
    print('ERROR:', type(e).__name__, str(e)[:200])