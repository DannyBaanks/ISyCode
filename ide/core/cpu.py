"""
core/cpu.py -- GOLDEN 4a: CPU minima stack-based, ciclo fetch-decode-
execute-writeback, con separacion Harvard real (no best-effort) entre
codigo y datos. Mismo patron "verificar antes de ejecutar"
(cobol_rigor_static_first, ya citado en README.md via el precedente del
verifier de eBPF) que sandbox/interp.py: validate_program() primero,
run() despues.

Por que existe junto a Layer_a (sandbox/interp.py): Layer_a es un filtro
best-effort sobre Python real -- el grafo de objetos vivos sigue siendo
alcanzable via introspeccion (rexec/Bastion, RestrictedPython, ambos
rotos por la misma razon). Esta CPU no interpreta Python: ejecuta una
lista FIJA de tuplas (opcode, operando) ya validada. No hay opcode que
tome un valor del stack/memoria y lo trate como instruccion -- los
saltos SIEMPRE apuntan a un indice literal del programa (parte del
codigo), nunca a un valor calculado en tiempo de ejecucion (dato). Esa
es la separacion Harvard real: el segmento de codigo (list[Instruction])
y el segmento de datos (stack: list[int], memory: list[int]) son
objetos Python de tipos distintos, y no existe operacion que convierta
uno en otro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Optional

MAX_STEPS = 100_000
MAX_STACK = 1024
MEM_SIZE = 256

OPCODES = frozenset({
    "PUSH", "POP", "DUP", "SWAP",
    "ADD", "SUB", "MUL", "DIV",
    "JMP", "JZ",
    "STORE", "LOAD",
    "HALT",
})

_NEEDS_OPERAND = frozenset({"PUSH", "JMP", "JZ", "STORE", "LOAD"})


class Instruction(NamedTuple):
    op: str
    arg: Optional[int] = None


class CPUFault(Exception):
    """Cualquier violacion se levanta con un nombre especifico -- nunca
    una excepcion generica de Python que filtre detalles de implementacion."""


class UnknownOpcode(CPUFault):
    pass


class InvalidOperand(CPUFault):
    pass


class JumpOutOfBounds(CPUFault):
    pass


class StackUnderflow(CPUFault):
    pass


class StackOverflow(CPUFault):
    pass


class MemoryOutOfBounds(CPUFault):
    pass


class DivisionByZero(CPUFault):
    pass


class StepLimitExceeded(CPUFault):
    pass


@dataclass
class CPUResult:
    halted: bool
    steps: int
    stack: list
    memory: list


def validate_program(program: list) -> None:
    """Ley harvard_separation / fixed_instruction_set: analiza TODO el
    programa antes de ejecutar una sola instruccion. Nunca se llega a
    run() con un programa mal formado, un opcode desconocido, o un
    salto/direccion fuera de rango."""
    if not program:
        raise InvalidOperand("programa vacio")
    n = len(program)
    for i, instr in enumerate(program):
        if not isinstance(instr, Instruction):
            raise InvalidOperand(f"instruccion {i} no es Instruction: {instr!r}")
        if instr.op not in OPCODES:
            raise UnknownOpcode(f"opcode desconocido en instruccion {i}: {instr.op!r}")
        if instr.op in _NEEDS_OPERAND:
            if instr.arg is None or not isinstance(instr.arg, int) or isinstance(instr.arg, bool):
                raise InvalidOperand(f"instruccion {i} ({instr.op}) requiere operando entero")
        if instr.op in ("JMP", "JZ"):
            if not (0 <= instr.arg < n):
                raise JumpOutOfBounds(f"instruccion {i} ({instr.op}) salta fuera de rango: {instr.arg}")
        if instr.op in ("STORE", "LOAD"):
            if not (0 <= instr.arg < MEM_SIZE):
                raise MemoryOutOfBounds(f"instruccion {i} ({instr.op}) direccion fuera de rango: {instr.arg}")


def _pop(stack: list, pc: int) -> int:
    if not stack:
        raise StackUnderflow(f"stack vacio en pc={pc}")
    return stack.pop()


def run(program: list, max_steps: int = MAX_STEPS) -> CPUResult:
    """validate_program() SIEMPRE antes de ejecutar (ley
    static_verify_before_exec / cobol_rigor_static_first). Ciclo
    fetch-decode-execute-writeback explicito por instruccion."""
    validate_program(program)

    stack: list = []
    memory: list = [0] * MEM_SIZE
    pc = 0
    steps = 0
    n = len(program)

    while True:
        if steps >= max_steps:
            raise StepLimitExceeded(f"excedio {max_steps} pasos (pc={pc})")
        if not (0 <= pc < n):
            raise JumpOutOfBounds(f"program counter fuera de rango: {pc}")

        # --- fetch ---
        instr = program[pc]
        # --- decode ---
        op, arg = instr.op, instr.arg
        # --- execute + writeback ---
        next_pc = pc + 1

        if op == "PUSH":
            if len(stack) >= MAX_STACK:
                raise StackOverflow(f"stack lleno en pc={pc}")
            stack.append(arg)
        elif op == "POP":
            _pop(stack, pc)
        elif op == "DUP":
            if not stack:
                raise StackUnderflow(f"DUP sobre stack vacio en pc={pc}")
            if len(stack) >= MAX_STACK:
                raise StackOverflow(f"stack lleno en pc={pc}")
            stack.append(stack[-1])
        elif op == "SWAP":
            if len(stack) < 2:
                raise StackUnderflow(f"SWAP requiere 2 valores en pc={pc}")
            stack[-1], stack[-2] = stack[-2], stack[-1]
        elif op in ("ADD", "SUB", "MUL", "DIV"):
            b = _pop(stack, pc)
            a = _pop(stack, pc)
            if op == "ADD":
                stack.append(a + b)
            elif op == "SUB":
                stack.append(a - b)
            elif op == "MUL":
                stack.append(a * b)
            else:
                if b == 0:
                    raise DivisionByZero(f"division por cero en pc={pc}")
                stack.append(a // b)
        elif op == "JMP":
            next_pc = arg
        elif op == "JZ":
            v = _pop(stack, pc)
            if v == 0:
                next_pc = arg
        elif op == "STORE":
            v = _pop(stack, pc)
            memory[arg] = v
        elif op == "LOAD":
            if len(stack) >= MAX_STACK:
                raise StackOverflow(f"stack lleno en pc={pc}")
            stack.append(memory[arg])
        elif op == "HALT":
            return CPUResult(halted=True, steps=steps, stack=list(stack), memory=list(memory))
        else:
            raise UnknownOpcode(f"opcode desconocido en ejecucion: {op!r}")  # inalcanzable

        pc = next_pc
        steps += 1
