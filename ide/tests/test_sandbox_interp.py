import pytest
from sandbox.interp import run_program
from sandbox.exceptions import UnsafeOperationDetected


def test_runs_simple_safe_program():
    ns = run_program("x = 1 + 2\nresult = x * 10")
    assert ns["result"] == 30


def test_print_allowed_in_safe_builtins():
    run_program("print('hola desde el sandbox')")  # no debe levantar


def test_import_os_detected():
    with pytest.raises(UnsafeOperationDetected):
        run_program("import os\nos.system('echo hola')")


def test_import_subprocess_detected():
    with pytest.raises(UnsafeOperationDetected):
        run_program("import subprocess")


def test_open_call_detected():
    with pytest.raises(UnsafeOperationDetected):
        run_program("f = open('C:/Windows/System32/cmd.exe')")


def test_eval_call_detected():
    with pytest.raises(UnsafeOperationDetected):
        run_program("eval('1+1')")


def test_dunder_subclasses_escape_detected():
    # el vector real que rompio rexec/Bastion en Python real
    payload = "x = ().__class__.__bases__[0].__subclasses__()"
    with pytest.raises(UnsafeOperationDetected):
        run_program(payload)


def test_dunder_import_builtin_detected():
    with pytest.raises(UnsafeOperationDetected):
        run_program("m = __import__('os')")


def test_getattr_bypass_detected():
    # getattr con string podria evadir un chequeo que solo mire ast.Attribute
    payload = "cls = getattr((), '__class__')"
    with pytest.raises(UnsafeOperationDetected):
        run_program(payload)
