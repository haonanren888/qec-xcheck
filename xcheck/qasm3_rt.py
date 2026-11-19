"""Qiskit circuit → qasm3.dumps → qasm3.loads.

Compared:
- gate sequence (name, qubit indexes, clbit indexes, parameters)
- classical condition bits and integer value
- control-flow bodies
- Operator equivalence when the circuit is unitary (no measure, reset,
  barrier, or control flow)

A one-bit condition value of True and 1 is the same OpenQASM bit test.
`if (c[0])` loads back as True. A register compare such as `c == 2`
keeps the integer. Loop-parameter names created by the exporter are
placeholders; the iteration values and the body expression shape are compared.
"""

from __future__ import annotations

import time

from qiskit import QuantumCircuit
from qiskit.circuit import (
    ClassicalRegister,
    Clbit,
    ForLoopOp,
    IfElseOp,
    Parameter,
    ParameterExpression,
    WhileLoopOp,
)
from qiskit.qasm3 import dumps, loads
from qiskit.quantum_info import Operator

_NON_UNITARY = {"measure", "reset", "barrier"}


def _clbit_indexes(root: QuantumCircuit, target) -> tuple:
    if isinstance(target, Clbit):
        return (root.find_bit(target).index,)
    if isinstance(target, ClassicalRegister):
        return tuple(root.find_bit(bit).index for bit in target)
    return ("unparsed", type(target).__name__, str(target))


def _condition_value(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return ("unparsed", type(value).__name__, str(value))


def _condition(root: QuantumCircuit, condition):
    if condition is None:
        return None
    if isinstance(condition, tuple) and len(condition) == 2:
        return {
            "bits": _clbit_indexes(root, condition[0]),
            "value": _condition_value(condition[1]),
        }
    return ("unparsed", type(condition).__name__, str(condition))


def _rewrite(value, loop_parameter):
    if isinstance(value, (int, float)):
        return round(float(value), 12)
    if loop_parameter is None:
        if isinstance(value, Parameter):
            return ("param", value.name)
        if isinstance(value, ParameterExpression):
            return ("expr", str(value))
        return ("other", str(value))
    placeholder = Parameter("_i")
    if isinstance(value, Parameter) and value == loop_parameter:
        return ("param", "_i")
    if isinstance(value, ParameterExpression) and loop_parameter in value.parameters:
        rewritten = value.assign(loop_parameter, placeholder)
        return ("expr", str(rewritten))
    if isinstance(value, ParameterExpression):
        return ("expr", str(value))
    return ("other", str(value))


def _params(operation, loop_parameter) -> tuple:
    raw = getattr(operation, "params", ()) or ()
    return tuple(_rewrite(item, loop_parameter) for item in raw)


def _indexes(root: QuantumCircuit, bits) -> tuple[int, ...]:
    return tuple(root.find_bit(bit).index for bit in bits)


def structure(circuit: QuantumCircuit) -> list:
    return _walk(circuit, circuit, None)


def _walk(circuit: QuantumCircuit, root: QuantumCircuit, loop_parameter) -> list:
    rows = []
    for instruction in circuit.data:
        operation = instruction.operation
        qubits = _indexes(root, instruction.qubits)
        clbits = _indexes(root, instruction.clbits)
        if isinstance(operation, IfElseOp):
            bodies = [_walk(block, root, loop_parameter) for block in operation.blocks]
            rows.append(
                (
                    "if_else",
                    qubits,
                    clbits,
                    _condition(root, operation.condition),
                    tuple(bodies),
                )
            )
            continue
        if isinstance(operation, WhileLoopOp):
            rows.append(
                (
                    "while_loop",
                    qubits,
                    clbits,
                    _condition(root, operation.condition),
                    tuple(_walk(operation.blocks[0], root, loop_parameter)),
                )
            )
            continue
        if isinstance(operation, ForLoopOp):
            indexset = tuple(operation.params[0])
            parameter = operation.params[1]
            if parameter is not None and not isinstance(parameter, Parameter):
                parameter = None
            body = _walk(operation.blocks[0], root, parameter)
            rows.append(("for_loop", qubits, clbits, indexset, tuple(body)))
            continue
        rows.append(
            (
                operation.name,
                qubits,
                clbits,
                _params(operation, loop_parameter),
            )
        )
    return rows


def _unitary(circuit: QuantumCircuit) -> bool:
    if circuit.num_clbits:
        return False
    for instruction in circuit.data:
        operation = instruction.operation
        if operation.name in _NON_UNITARY or isinstance(
            operation, (IfElseOp, WhileLoopOp, ForLoopOp)
        ):
            return False
    return True


def check_circuit(circuit: QuantumCircuit, case_id: str, note: str = "") -> dict:
    started = time.perf_counter()
    broken: list[str] = []
    detail = ""
    invariants: dict = {
        "qubits": [circuit.num_qubits],
        "clbits": [circuit.num_clbits],
    }
    status = "pass"
    try:
        text = dumps(circuit)
        back = loads(text)
        invariants["qubits"].append(back.num_qubits)
        invariants["clbits"].append(back.num_clbits)
        if circuit.num_qubits != back.num_qubits:
            broken.append("qubit_count")
        if circuit.num_clbits != back.num_clbits:
            broken.append("clbit_count")
        original_structure = structure(circuit)
        back_structure = structure(back)
        invariants["gate_sequence_equal"] = original_structure == back_structure
        if original_structure != back_structure:
            broken.append("gate_sequence")
            detail = _first_diff(original_structure, back_structure)
        if _unitary(circuit) and _unitary(back):
            try:
                same = bool(Operator(circuit).equiv(Operator(back)))
            except Exception as exc:
                same = False
                detail = f"Operator: {type(exc).__name__}: {exc}"
            invariants["operator_equal"] = same
            if not same:
                broken.append("operator")
        else:
            invariants["operator_equal"] = None
    except Exception as exc:
        status = "error"
        broken = ["exception"]
        detail = f"{type(exc).__name__}: {exc}"
    if status != "error" and broken:
        status = "mismatch"
    return {
        "check": "qasm3-roundtrip",
        "case_id": case_id,
        "status": status,
        "seconds": round(time.perf_counter() - started, 6),
        "broken": broken,
        "invariants": invariants,
        "detail": detail[:800],
        "classification": None,
        "notes": [{"kind": "spec_note", "detail": note}] if note else [],
    }


def check_file(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return check_circuit(loads(text), path)


def _first_diff(left, right) -> str:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return f"index {index}: {left[index]!r} -> {right[index]!r}"
    return f"length {len(left)} -> {len(right)}"
