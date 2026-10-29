from isycode.streaming import detect_unexecuted_tool_request


def test_detects_a_shell_tool_json_object_as_not_executed():
    response = '{"tool": "bash", "args": ["ls", "-la"]}'

    assert detect_unexecuted_tool_request(response) == "bash"


def test_detects_a_fenced_shell_tool_json_object():
    response = '```json\n{"tool":"bash","args":["pwd"]}\n```'

    assert detect_unexecuted_tool_request(response) == "bash"


def test_does_not_treat_normal_json_or_prose_as_a_tool_call():
    assert detect_unexecuted_tool_request('{"tool_count": 3}') is None
    assert detect_unexecuted_tool_request('Use `bash` to list files.') is None
    assert detect_unexecuted_tool_request('{"tool":"browser","args":[]}') is None


def test_rejects_malformed_or_unbounded_tool_arguments():
    assert detect_unexecuted_tool_request('{"tool":"bash","args":"ls"}') is None
    assert detect_unexecuted_tool_request('{"tool":"bash","args":[]} trailing') is None
