from core.todo import TodoStore


def test_todo_store_persists_and_toggles(tmp_path):
    store = TodoStore(tmp_path)
    item = store.add("review resident guidance")
    assert store.list()[0]["status"] == "open"
    assert "review resident guidance" in store.summary()
    store.toggle(item["id"])
    assert store.list()[0]["status"] == "done"
    assert store.summary() == "TODO: clear"
