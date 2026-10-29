import pytest

from isycode.semantic_gateway import OPERATIONS, validate_semantic_payload


def test_all_semantic_operations_have_strict_payload_contracts():
    valid = {
        "context": {"query": "Widget"},
        "symbols/search": {"query": "Widget"},
        "document-symbols": {"path": "src/widget.py"},
        "definition": {"target": "src/widget.py::Widget"},
        "references": {"symbol": "Widget"},
        "hover": {"target": "src/widget.py::Widget"},
        "diagnostics": {"path": "src/widget.py"},
        "semantic-slice": {"target": "src/widget.py::Widget"},
        "implementations": {"symbol": "Widget"},
        "callers": {"symbol": "Widget"},
        "callees": {"symbol": "Widget"},
    }
    assert set(valid) == set(OPERATIONS)
    for operation, payload in valid.items():
        assert validate_semantic_payload(operation, payload) == payload


@pytest.mark.parametrize("payload", [
    {"query": "Widget", "workspace_id": "unexpected"},
    {"query": "Widget", "max_results": True},
    {"query": "Widget", "include": "src"},
])
def test_semantic_payload_rejects_unknown_or_mistyped_values(payload):
    with pytest.raises(ValueError):
        validate_semantic_payload("symbols/search", payload)


def test_operation_specific_required_fields_are_enforced():
    with pytest.raises(ValueError):
        validate_semantic_payload("diagnostics", {})
    with pytest.raises(ValueError):
        validate_semantic_payload("symbols/search", {"query": " "})


def test_frozen_action_parameters_accept_tuple_backed_include_lists():
    assert validate_semantic_payload("symbols/search", {
        "query": "Widget", "include": ("python",),
    })["include"] == ["python"]
