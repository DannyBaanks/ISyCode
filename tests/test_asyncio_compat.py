import asyncio
import gc
from unittest.mock import MagicMock

import pytest

from isycode.asyncio_compat import cancel_requested, note_cancel_requested


@pytest.mark.asyncio
async def test_cancel_requested_none():
    assert cancel_requested(None) is False


@pytest.mark.asyncio
async def test_cancel_requested_running_task():
    async def dummy():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy())
    assert cancel_requested(task) is False
    await task


@pytest.mark.asyncio
async def test_note_cancel_requested_fallback():
    async def dummy():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy())

    # Test explicit note_cancel_requested
    note_cancel_requested(task)
    # If python 3.11+, cancelling() returns 0 until task.cancel() is called,
    # but let's test the mock without native cancelling attribute as well.
    mock_task = MagicMock(spec=[])  # No cancelling attr
    assert cancel_requested(mock_task) is False
    note_cancel_requested(mock_task)
    assert cancel_requested(mock_task) is True

    await task


@pytest.mark.asyncio
async def test_cancel_requested_with_native_cancelling():
    mock_task = MagicMock()
    mock_task.cancelling.return_value = 0
    assert cancel_requested(mock_task) is False

    mock_task.cancelling.return_value = 1
    assert cancel_requested(mock_task) is True


@pytest.mark.asyncio
async def test_note_cancel_requested_weakset_no_leak():
    class DummyTask:
        pass

    obj = DummyTask()
    note_cancel_requested(obj)  # type: ignore[arg-type]
    assert cancel_requested(obj)  # type: ignore[arg-type]

    del obj
    gc.collect()
    # WeakSet drops collected objects without error
