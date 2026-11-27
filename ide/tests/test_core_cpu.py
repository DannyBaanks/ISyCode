import pytest
from core.cpu import (
    Instruction as I, run, validate_program,
    UnknownOpcode, JumpOutOfBounds, StackUnderflow, StackOverflow,
    MemoryOutOfBounds, DivisionByZero, StepLimitExceeded, InvalidOperand,
)


def test_arithmetic_halts_with_expected_result():
    program = [
        I("PUSH", 3), I("PUSH", 4), I("ADD"),
        I("PUSH", 2), I("MUL"),
        I("HALT"),
    ]
    result = run(program)
    assert result.halted
    assert result.stack == [14]


def test_loop_with_jz_and_memory_halts_with_expected_countdown():
    program = [
        I("PUSH", 3), I("STORE", 0),           # 0,1
        I("LOAD", 0), I("JZ", 9),               # 2,3 -> HALT en 9
        I("LOAD", 0), I("PUSH", 1), I("SUB"),   # 4,5,6
        I("STORE", 0),                           # 7
        I("JMP", 2),                             # 8 -> vuelve a 2
        I("HALT"),                               # 9
    ]
    result = run(program)
    assert result.halted
    assert result.memory[0] == 0


def test_unknown_opcode_rejected_statically():
    program = [I("NOPE", 1), I("HALT")]
    with pytest.raises(UnknownOpcode):
        validate_program(program)
    with pytest.raises(UnknownOpcode):
        run(program)


def test_jump_out_of_bounds_rejected_statically():
    program = [I("JMP", 99), I("HALT")]
    with pytest.raises(JumpOutOfBounds):
        validate_program(program)


def test_memory_out_of_bounds_rejected_statically():
    program = [I("PUSH", 1), I("STORE", 9999), I("HALT")]
    with pytest.raises(MemoryOutOfBounds):
        validate_program(program)


def test_stack_underflow_on_pop_empty():
    program = [I("POP"), I("HALT")]
    with pytest.raises(StackUnderflow):
        run(program)


def test_division_by_zero():
    program = [I("PUSH", 5), I("PUSH", 0), I("DIV"), I("HALT")]
    with pytest.raises(DivisionByZero):
        run(program)


def test_step_limit_exceeded_on_infinite_loop():
    program = [I("JMP", 0)]
    with pytest.raises(StepLimitExceeded):
        run(program, max_steps=1000)


def test_stack_overflow_on_unbounded_push_loop():
    program = [I("PUSH", 1), I("JMP", 0)]
    with pytest.raises(StackOverflow):
        run(program, max_steps=10_000_000)


def test_invalid_operand_type_rejected_statically():
    program = [I("PUSH", "no-es-int"), I("HALT")]
    with pytest.raises(InvalidOperand):
        validate_program(program)
