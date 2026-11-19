"""Minimal circuits. Each constructor stays within 15 lines."""

from __future__ import annotations

import cirq
import sympy


def circuit_8525() -> cirq.Circuit:
    q0, q1 = cirq.LineQubit.range(2)
    body = cirq.FrozenCircuit(
        cirq.measure(q0, key="m"),
        cirq.X(q0),
        cirq.measure(q0, key="m"),
        cirq.X(q1).with_classical_controls(cirq.KeyCondition(cirq.MeasurementKey("m"), 0)),
        cirq.measure(q1, key="out"),
    )
    return cirq.Circuit(cirq.CircuitOperation(body))


def circuit_8525_json() -> cirq.Circuit:
    q0, q1 = cirq.LineQubit.range(2)
    return cirq.Circuit(
        cirq.measure(q0, key="m"),
        cirq.X(q0),
        cirq.measure(q0, key="m"),
        cirq.X(q1).with_classical_controls(cirq.KeyCondition(cirq.MeasurementKey("m"), 0)),
        cirq.measure(q1, key="out"),
    )


def circuit_8525_mask() -> cirq.Circuit:
    q0, q1, q2 = cirq.LineQubit.range(3)
    cond = cirq.BitMaskKeyCondition(
        cirq.MeasurementKey("m"), target_value=1, equal_target=True, bitmask=1
    )
    ops = [
        cirq.X(q0),
        cirq.measure(q0, q1, key="m"),
        cirq.X(q2).with_classical_controls(cond),
        cirq.measure(q2, key="out"),
    ]
    return cirq.Circuit(cirq.CircuitOperation(cirq.FrozenCircuit(ops)))


def circuit_8528() -> cirq.Circuit:
    q0, q1 = cirq.LineQubit.range(2)
    cond = cirq.SympyCondition(sympy.Symbol("m", positive=True))
    return cirq.Circuit(
        cirq.measure(q0, key="m"),
        cirq.X(q1).with_classical_controls(cond),
        cirq.measure(q1, key="out"),
    )


def circuit_8529() -> cirq.Circuit:
    q0, q1, q2 = cirq.LineQubit.range(3)
    a, b = sympy.symbols("a b")
    circuit = cirq.Circuit(
        cirq.X(q0),
        cirq.measure(q0, key="a"),
        cirq.measure(q1, key="b"),
        cirq.X(q2).with_classical_controls(cirq.SympyCondition(a > b)),
        cirq.measure(q2, key="out"),
    )
    return cirq.with_measurement_key_mapping(circuit, {"a": "b", "b": "a"})


def circuit_8530() -> cirq.Circuit:
    q0, q1, out = cirq.LineQubit.range(3)
    return cirq.Circuit(
        cirq.X(q0),
        cirq.measure(q0, q1, key="m"),
        cirq.X(out).with_classical_controls(sympy.Eq(sympy.Symbol("m"), 2)),
        cirq.measure(out, key="out"),
    )


def circuit_1143() -> cirq.Circuit:
    q0, q1, q2 = cirq.LineQubit.range(3)
    return cirq.Circuit(
        cirq.measure(q1, key="a"),
        cirq.X(q0),
        cirq.measure(q0, key="a"),
        cirq.X(q2).with_classical_controls(cirq.KeyCondition(cirq.MeasurementKey("a"), 0)),
        cirq.measure(q2, key="out"),
    )


def circuit_1144() -> cirq.Circuit:
    import numpy as np

    q = cirq.LineQubit(0)
    cm = np.array([[1.0, 0.0], [1.0, 0.0]])
    measured = cirq.measure(q, key="out", confusion_map={(0,): cm})
    return cirq.Circuit(cirq.X(q), measured)


def circuit_1142() -> cirq.Circuit:
    q0, q1 = cirq.LineQubit.range(2)
    gate = cirq.ControlledGate(cirq.DensePauliString("Z"), control_values=(0,))
    return cirq.Circuit(cirq.H(q1), gate.on(q0, q1), cirq.H(q1), cirq.measure(q1, key="out"))


def circuit_1136() -> cirq.Circuit:
    q0, q1, q2 = cirq.LineQubit.range(3)
    body = cirq.Circuit(cirq.measure(q0, key="b")).freeze()
    op = cirq.CircuitOperation(body, repetitions=2, measurement_key_map={"b": "a"})
    return cirq.Circuit(
        cirq.X(q0),
        cirq.measure(q1, key="b"),
        op,
        cirq.X(q2).with_classical_controls("b"),
        cirq.measure(q2, key="out"),
    )


def circuit_1145() -> tuple[cirq.CircuitOperation, cirq.CircuitOperation]:
    q = cirq.LineQubit(0)
    body = cirq.FrozenCircuit(cirq.Moment(cirq.X(q)), cirq.Moment(cirq.measure(q, key="m")))
    inner = cirq.CircuitOperation(body, repetitions=2, use_repetition_ids=False)
    wrapped = cirq.CircuitOperation(
        cirq.FrozenCircuit(cirq.Moment(inner)),
        repetitions=1,
        use_repetition_ids=False,
    )
    return inner, wrapped
