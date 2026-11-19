"""Nested Cirq circuit vs unroll vs JSON, compared bit by bit.

Pass/fail follows the measurement records (or identical exceptions).
Condition-field changes that do not move the bits are notes: the nested
simulator and the unrolled circuit can share one bug and still agree.
"""

from __future__ import annotations

import json
import time

import cirq
import sympy


def _bits(circuit: cirq.Circuit) -> dict:
    try:
        result = cirq.Simulator().run(circuit)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    records = {}
    for key, value in result.records.items():
        records[str(key)] = [[int(bit) for bit in row] for row in value[0].tolist()]
    return {"bits": records}


def _condition_fields(circuit: cirq.Circuit) -> list[tuple]:
    found: list[tuple] = []

    def walk(current: cirq.AbstractCircuit) -> None:
        for operation in current.all_operations():
            if isinstance(operation, cirq.CircuitOperation):
                walk(operation.circuit)
            controls = getattr(operation, "classical_controls", ())
            for condition in controls:
                found.append(_one_condition(condition))

    walk(circuit)
    return found


def _one_condition(condition) -> tuple:
    if isinstance(condition, cirq.KeyCondition):
        return ("Key", condition.index)
    if isinstance(condition, cirq.BitMaskKeyCondition):
        return (
            "Mask",
            condition.index,
            condition.bitmask,
            condition.target_value,
            condition.equal_target,
        )
    if isinstance(condition, cirq.SympyCondition):
        names = []
        for symbol in condition.expr.free_symbols:
            if isinstance(symbol, sympy.Symbol):
                names.append((symbol.name, symbol != sympy.Symbol(symbol.name)))
        return ("Sym", str(condition.expr), tuple(sorted(names)))
    return (type(condition).__name__, str(condition))


def _has_assumed_symbol(circuit: cirq.Circuit) -> bool:
    for row in _condition_fields(circuit):
        if row[0] == "Sym" and any(assumed for _name, assumed in row[2]):
            return True
    return False


def _json_dropped_key_index(circuit: cirq.Circuit, restored: cirq.Circuit) -> bool:
    original = [row for row in _condition_fields(circuit) if row[0] == "Key"]
    back = [row for row in _condition_fields(restored) if row[0] == "Key"]
    if not any(index != -1 for _kind, index in original):
        return False
    return original != back and all(index == -1 for _kind, index in back)


def _notes(circuit: cirq.Circuit, restored: cirq.Circuit) -> list[dict]:
    notes: list[dict] = []
    try:
        flat = cirq.unroll_circuit_op(circuit, deep=True, tags_to_check=None)
        original = _condition_fields(circuit)
        unrolled = _condition_fields(flat)
    except Exception as exc:
        return [{"kind": "structural_scan_error", "detail": f"{type(exc).__name__}: {exc}"}]
    if original != unrolled:
        if _key_index_lost(original, unrolled):
            notes.append(
                {
                    "kind": "reported",
                    "id": "Cirq #8525",
                    "source": "cirq/value/condition.py:98-99 KeyCondition.replace_key",
                    "detail": (
                        "Unroll drops KeyCondition.index. "
                        "get_int documents 0 as the first record and -1 as the latest. "
                        "Nested and unrolled simulations can still agree."
                    ),
                }
            )
        if _mask_reset(original, unrolled):
            notes.append(
                {
                    "kind": "pending_same_root",
                    "id": "bitmask_replace_key",
                    "source": "cirq/value/condition.py:204-205 BitMaskKeyCondition.replace_key",
                    "detail": (
                        "Unroll rebuilds BitMaskKeyCondition(replacement) and drops "
                        "index, bitmask, target_value, and equal_target. "
                        "The class docstring defines those fields. Not in the reported-issue list."
                    ),
                }
            )
    restored_fields = _condition_fields(restored)
    if _json_dropped_key_index(circuit, restored) and all(
        item.get("id") != "json_drops_keycondition_index" for item in notes
    ):
        notes.append(_json_index_classification())
    return notes


def _key_index_lost(original, unrolled) -> bool:
    original_indexes = [row[1] for row in original if row[0] == "Key"]
    unrolled_indexes = [row[1] for row in unrolled if row[0] == "Key"]
    return any(index != -1 for index in original_indexes) and unrolled_indexes != original_indexes


def _mask_reset(original, unrolled) -> bool:
    original_masks = [row for row in original if row[0] == "Mask"]
    unrolled_masks = [row for row in unrolled if row[0] == "Mask"]
    if not original_masks or original_masks == unrolled_masks:
        return False
    return any(row != ("Mask", -1, None, 0, False) for row in original_masks)


def _json_index_classification() -> dict:
    return {
        "kind": "pending_same_root",
        "id": "json_drops_keycondition_index",
        "counts_as_new": False,
        "source": "cirq/value/condition.py:117-119 KeyCondition._from_json_dict_",
        "spec": (
            "classical_data.py get_int: index 0 is the first measurement and -1 is the most recent. "
            "KeyCondition.resolve passes that index through. "
            "_json_dict_ writes the dataclass field, and _from_json_dict_ keeps only key."
        ),
        "shortest_repro": (
            "m measured twice as 0 then 1; X on q1 controlled by KeyCondition(m, index=0); "
            "direct and unroll leave out=0; JSON read-back leaves out=1."
        ),
    }


def _symbol_classification() -> dict:
    return {
        "kind": "documented_limitation",
        "id": "json_symbol_name_only",
        "counts_as_new": False,
        "related_reported": "Cirq #8528",
        "source": "cirq/protocols/json_serialization.py:215-216 and 245-246",
        "spec": (
            "CirqEncoder documents preliminary SymPy support and stores sympy.Symbol by name only. "
            "Assumptions are outside that schema, so a positive Symbol comes back as a plain Symbol. "
            "The simulator result on the original circuit (positive Symbol stays true at measurement 0) "
            "is the already reported #8528, whose resolve path substitutes a plain Symbol."
        ),
        "shortest_repro": (
            "Measure q0 in |0> as m; control X with SympyCondition(Symbol('m', positive=True)); "
            "direct and unroll set out=1; JSON read-back sets out=0."
        ),
    }


def _classify(circuit, direct, unrolled, restored, restored_circuit) -> dict | None:
    if direct == unrolled == restored:
        return None
    if direct == unrolled and direct != restored and _json_dropped_key_index(circuit, restored_circuit):
        row = _json_index_classification()
        row["counts_as_new"] = False
        return row
    if direct == unrolled and direct != restored and _has_assumed_symbol(circuit):
        return _symbol_classification()
    return {
        "kind": "needs_spec_review",
        "id": "unclassified_bit_mismatch",
        "counts_as_new": False,
        "detail": "Bit mismatch does not match the JSON-index or Symbol-name patterns. Not counted as a new defect in this run.",
    }


def check_circuit(circuit: cirq.Circuit, case_id: str, *, use_oracle: bool = False) -> dict:
    started = time.perf_counter()
    direct = _bits(circuit)
    try:
        flat = cirq.unroll_circuit_op(circuit, deep=True, tags_to_check=None)
        unrolled = _bits(flat)
    except Exception as exc:
        unrolled = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        text = cirq.to_json(circuit)
        restored_circuit = cirq.read_json(json_text=text)
        restored = _bits(restored_circuit)
    except Exception as exc:
        restored_circuit = circuit
        restored = {"error": f"{type(exc).__name__}: {exc}"}
    broken: list[str] = []
    if direct != unrolled:
        broken.append("nested_vs_unroll")
    if direct != restored:
        broken.append("nested_vs_json")
    if unrolled != restored:
        broken.append("unroll_vs_json")
    reference = None
    if use_oracle:
        from xcheck.classical_ref import run as oracle_run

        try:
            reference = {"bits": oracle_run(circuit)}
        except Exception as exc:
            reference = {"error": f"{type(exc).__name__}: {exc}"}
        if "bits" not in reference:
            broken.append("oracle")
        else:
            for label, observed in (
                ("nested", direct),
                ("unroll", unrolled),
                ("json", restored),
            ):
                if observed != reference:
                    broken.append(f"{label}_vs_oracle")
    status = "mismatch" if broken else "pass"
    classification = _classify(circuit, direct, unrolled, restored, restored_circuit)
    notes = []
    if status == "pass":
        try:
            notes = _notes(circuit, restored_circuit if isinstance(restored_circuit, cirq.AbstractCircuit) else circuit)
        except Exception as exc:
            notes = [{"kind": "structural_scan_error", "detail": f"{type(exc).__name__}: {exc}"}]
    elif classification and classification.get("id") == "json_drops_keycondition_index":
        notes = [classification]
    return {
        "check": "cirq-classical-control",
        "case_id": case_id,
        "status": status,
        "seconds": round(time.perf_counter() - started, 6),
        "broken": broken,
        "invariants": {
            "direct": direct,
            "unrolled": unrolled,
            "json": restored,
            **({"oracle": reference} if reference is not None else {}),
        },
        "detail": "",
        "classification": classification,
        "notes": notes,
    }


def _stored_key_indexes(text: str) -> list[int]:
    found: list[int] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("cirq_type") == "KeyCondition" and "index" in node:
                found.append(int(node["index"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(text))
    return found


def check_file(path: str, *, use_oracle: bool = False) -> dict:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    circuit = cirq.read_json(json_text=text)
    result = check_circuit(circuit, path, use_oracle=use_oracle)
    stored = _stored_key_indexes(text)
    loaded = [row[1] for row in _condition_fields(circuit) if row[0] == "Key"]
    if stored != loaded and any(index != -1 for index in stored):
        result["status"] = "mismatch"
        if "json_file_vs_object" not in result["broken"]:
            result["broken"] = [*result["broken"], "json_file_vs_object"]
        result["classification"] = _json_index_classification()
        result["invariants"]["json_file_indexes"] = stored
        result["invariants"]["loaded_indexes"] = loaded
        result["notes"] = [result["classification"]]
    return result
