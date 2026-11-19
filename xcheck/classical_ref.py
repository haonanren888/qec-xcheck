"""Independent reference for Cirq classical control.

Reads only circuit structure: gates, keys, condition fields, and
CircuitOperation repetitions, measurement_key_map, repetition_ids,
use_repetition_ids, parent_path, and qubit_map. Condition values and key
prefixes are computed here from the Cirq documentation. This module does not
call Condition.resolve, replace_key, or CircuitOperation.mapped_circuit.

Documented rules:
- KeyCondition is true when the integer at index is non-zero. 0 is the
  earliest record and -1 is the latest.
- BitMaskKeyCondition compares (value & bitmask) with target_value using
  == or !=. The integer is big-endian, so the first qubit is the high bit.
  index means the same thing as on KeyCondition.
- SympyCondition substitutes the measurement integer for a symbol and the
  big-endian bits for an IndexedBase, then takes bool(result). Substitution
  uses the symbol object, so assumptions on the symbol do not block it.
- CircuitOperation.use_repetition_ids: when true, each repeat adds that
  repetition id to the measurement-key path. When false, repeats append to
  the same key.
- measurement_key_map renames keys by name and rewrites that same name inside
  conditions. All keys are renamed together, not one replacement at a time.
- parent_path is applied after the repetition id. The final path is
  parent_path + (rep_id,) + the original path, in the same two stages as
  with_rescoped_keys.
- A condition key moves under a prefix only when an earlier moment already
  measured that prefixed key, or an externally bound key matches. Otherwise
  it keeps the renamed key so it can read an outer measurement.
- Renames and added path elements keep index, bitmask, target_value, and
  equal_target.
"""

from __future__ import annotations

import cirq
import sympy


def _fmt(path, name: str) -> str:
    path = tuple(path)
    if not path:
        return name
    return ":".join((*path, name))


def _path_len(key: str) -> int:
    return key.count(":")


def _prefix_key(key: str, prefix: tuple[str, ...]) -> str:
    if not prefix:
        return key
    return ":".join(prefix) + ":" + key


def _bits_to_int(bits) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def _measurement_key(op):
    raw = op.gate.key
    if isinstance(raw, str):
        return cirq.MeasurementKey(raw)
    return raw


def _as_bool(value) -> bool:
    if value in (sympy.true, True):
        return True
    if value in (sympy.false, False):
        return False
    if isinstance(value, (int, sympy.Integer)) or getattr(value, "is_integer", False):
        return bool(int(value))
    return bool(value)


def _eval_sympy(expr, resolve_int, resolve_bits) -> bool:
    indexed = {}
    for idx in expr.atoms(sympy.Indexed):
        label = idx.base.label
        name = str(label)
        bit_index = int(idx.indices[0])
        bits = resolve_bits(name)
        indexed[idx] = bits[bit_index]
    reduced = expr.xreplace(indexed) if indexed else expr
    if not hasattr(reduced, "free_symbols"):
        return _as_bool(reduced)
    values = {}
    for sym in reduced.free_symbols:
        if isinstance(sym, sympy.Symbol):
            values[sym] = resolve_int(sym.name)
    value = reduced.xreplace(values) if values else reduced
    return _as_bool(value)


class _World:
    def __init__(self):
        self.state: dict = {}
        self.records: dict[str, list[list[int]]] = {}

    def flip(self, qubit) -> None:
        self.state[qubit] = 1 - self.state.get(qubit, 0)

    def bit(self, qubit) -> int:
        return self.state.get(qubit, 0)


def _condition_holds(cond, resolve_key, records) -> bool:
    if isinstance(cond, cirq.KeyCondition):
        key = resolve_key(cond.key.name, cond.key.path)
        return _bits_to_int(records[key][cond.index]) != 0
    if isinstance(cond, cirq.BitMaskKeyCondition):
        key = resolve_key(cond.key.name, cond.key.path)
        value = _bits_to_int(records[key][cond.index])
        if cond.bitmask is not None:
            value &= cond.bitmask
        if cond.equal_target:
            return value == cond.target_value
        return value != cond.target_value
    if isinstance(cond, cirq.SympyCondition):
        def resolve_int(name, _path=()):
            key = resolve_key(name, _path)
            return _bits_to_int(records[key][-1])

        def resolve_bits(name, _path=()):
            key = resolve_key(name, _path)
            return tuple(records[key][-1])

        return _eval_sympy(cond.expr, resolve_int, resolve_bits)
    raise TypeError(f"unsupported condition type: {type(cond)!r}")


def _resolve_key(name, path, name_fn, rep_prefix, parent_prefix, p1_snap, p2_snap) -> str:
    mapped = name_fn(name)
    path = tuple(path)
    chosen = path
    for i in range(len(rep_prefix) + 1):
        back = rep_prefix[: len(rep_prefix) - i]
        cand_path = back + path
        if _fmt(cand_path, mapped) in p1_snap:
            chosen = cand_path
            break
    for i in range(len(parent_prefix) + 1):
        back = parent_prefix[: len(parent_prefix) - i]
        cand_path = back + chosen
        cand = _fmt(cand_path, mapped)
        if cand in p2_snap:
            return cand
    return _fmt(chosen, mapped)


def _run_circuit(circuit, world, rep_prefix, parent_prefix, name_fn, qubit_fn, extern) -> None:
    phase1: set[str] = set()
    phase2: set[str] = set(extern)
    for moment in circuit:
        p1_snap = set(phase1)
        p2_snap = set(phase2)
        new_p1: set[str] = set()
        new_p2: set[str] = set()
        for op in moment:
            if isinstance(op, cirq.CircuitOperation):
                _enter_co(
                    op,
                    world,
                    rep_prefix,
                    parent_prefix,
                    name_fn,
                    qubit_fn,
                    p1_snap,
                    p2_snap,
                )
            else:
                produced = _exec_leaf(
                    op,
                    world,
                    rep_prefix,
                    parent_prefix,
                    name_fn,
                    qubit_fn,
                    p1_snap,
                    p2_snap,
                )
                new_p1 |= produced[0]
                new_p2 |= produced[1]
        phase1 |= new_p1
        phase2 |= new_p2


def _enter_co(co, world, rep_prefix, parent_prefix, name_fn, qubit_fn, p1_snap, p2_snap) -> None:
    if co.repeat_until is not None:
        raise NotImplementedError("repeat_until is outside this reference")
    reps = int(co.repetitions)
    inner_map = dict(co.measurement_key_map)
    inner_qubits = dict(co.qubit_map)

    def composed_name(name, _inner=inner_map, _outer=name_fn):
        return _outer(_inner.get(name, name))

    def composed_qubit(qubit, _inner=inner_qubits, _outer=qubit_fn):
        return _outer(_inner.get(qubit, qubit))

    p1_filtered = {key for key in p1_snap if _path_len(key) <= len(rep_prefix)}
    p2_filtered = {key for key in p2_snap if _path_len(key) <= len(parent_prefix)}
    extern = set(p2_filtered)
    for key in p1_filtered:
        extern.add(_prefix_key(key, parent_prefix))
    parent2 = parent_prefix + rep_prefix + tuple(co.parent_path)
    ids = None
    if co.use_repetition_ids and co.repetition_ids:
        ids = list(co.repetition_ids)
    for i in range(reps):
        rep = (ids[i],) if ids is not None else ()
        _run_circuit(
            co.circuit,
            world,
            rep,
            parent2,
            composed_name,
            composed_qubit,
            extern,
        )


def _exec_leaf(op, world, rep_prefix, parent_prefix, name_fn, qubit_fn, p1_snap, p2_snap):
    def resolve_key(name, path):
        return _resolve_key(
            name, path, name_fn, rep_prefix, parent_prefix, p1_snap, p2_snap
        )

    if isinstance(op, cirq.ClassicallyControlledOperation):
        if all(_condition_holds(c, resolve_key, world.records) for c in op.classical_controls):
            return _exec_leaf(
                op.without_classical_controls(),
                world,
                rep_prefix,
                parent_prefix,
                name_fn,
                qubit_fn,
                p1_snap,
                p2_snap,
            )
        return set(), set()

    gate = getattr(op, "gate", None)
    if isinstance(gate, cirq.MeasurementGate):
        mk = _measurement_key(op)
        mapped = name_fn(mk.name)
        invert = tuple(gate.invert_mask or ())
        bits = []
        for i, qubit in enumerate(op.qubits):
            bit = world.bit(qubit_fn(qubit))
            if i < len(invert) and invert[i]:
                bit ^= 1
            bits.append(bit)
        full = _fmt(parent_prefix + rep_prefix + tuple(mk.path), mapped)
        world.records.setdefault(full, []).append(bits)
        p1 = _fmt(rep_prefix + tuple(mk.path), mapped)
        return {p1}, {full}

    if isinstance(gate, cirq.XPowGate) and gate.exponent == 1:
        world.flip(qubit_fn(op.qubits[0]))
        return set(), set()

    if isinstance(gate, cirq.CXPowGate) and gate.exponent == 1:
        control, target = (qubit_fn(q) for q in op.qubits)
        if world.bit(control) == 1:
            world.flip(target)
        return set(), set()

    raise TypeError(f"reference interpreter rejected operation: {op!r}")


def run(circuit) -> dict[str, list[list[int]]]:
    """Run the circuit from the all-zero state. Return {key: [[bits], ...]}."""
    world = _World()
    _run_circuit(
        circuit,
        world,
        rep_prefix=(),
        parent_prefix=(),
        name_fn=lambda name: name,
        qubit_fn=lambda qubit: qubit,
        extern=set(),
    )
    return {key: [list(bits) for bits in rows] for key, rows in world.records.items()}
