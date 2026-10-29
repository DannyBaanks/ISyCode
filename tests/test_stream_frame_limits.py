"""Protocol frame bounds are not generation or conversation token limits."""
import pytest

from isycode.streaming import StreamError
from test_daily_transport_regressions import local_completion


def test_oversized_sse_frame_is_rejected_without_echoing_its_body(monkeypatch):
    event = {'choices': [{'delta': {'content': 'x' * (1024 * 1024 + 1)},
                          'finish_reason': 'stop'}]}
    with pytest.raises(StreamError, match='frame'):
        local_completion(monkeypatch, [event, '[DONE]'])
