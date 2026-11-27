import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from ui.app import AppController
import tempfile

tmp = tempfile.mkdtemp()
c = AppController(tmp)

# Check providers loaded
print('Providers:')
for name, config in c.providers().items():
    has_key = c.has_key(name)
    print(f'  {name}: provider={config.get("provider")}, model={config.get("model")}, key={has_key}')

# Check provider types
print('Provider types:', c.provider_types())

# Try to get NVIDIA provider
try:
    provider = c.provider_registry.get('NVIDIA')
    print('NVIDIA provider resolved:', type(provider).__name__)
except Exception as e:
    print('NVIDIA error:', e)

# Try to get probe_nvidia provider
try:
    provider = c.provider_registry.get('probe_nvidia')
    print('probe_nvidia provider resolved:', type(provider).__name__)
except Exception as e:
    print('probe_nvidia error:', e)