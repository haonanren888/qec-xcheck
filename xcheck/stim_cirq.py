"""Stim → Cirq → Stim round trip.

Invariants, from the check definition:
- detector count
- observable count
- detector_error_model(decompose_errors=False), as a multiset of
  (error mechanism, probability)
- when the circuit has no noise instructions, one-shot detector samples

Extra TICKs are not an invariant. cirq_circuit_to_stim_circuit documents
that each Cirq moment becomes a TICK, so a round trip can insert TICKs.
"""

from __future__ import annotations

import math
import time

import stim
import stimcirq

_NOISE = {
    "CORRELATED_ERROR",
    "DEPOLARIZE1",
    "DEPOLARIZE2",
    "E",
    "ELSE_CORRELATED_ERROR",
    "HERALDED_ERASE",
    "HERALDED_PAULI_CHANNEL_1",
    "PAULI_CHANNEL_1",
    "PAULI_CHANNEL_2",
    "X_ERROR",
    "Y_ERROR",
    "Z_ERROR",
}


def _walk(circuit: stim.Circuit):
    for inst in circuit:
        if inst.name == "REPEAT":
            yield from _walk(inst.body_copy())
        else:
            yield inst


def has_noise(circuit: stim.Circuit) -> bool:
    return any(inst.name in _NOISE for inst in _walk(circuit))


def dem_rows(dem: stim.DetectorErrorModel) -> list[tuple[tuple[str, ...], float]]:
    rows: list[tuple[tuple[str, ...], float]] = []
    for inst in dem:
        if inst.type != "error":
            continue
        mechanism: list[str] = []
        for target in inst.targets_copy():
            if target.is_separator():
                mechanism.append("^")
            elif target.is_relative_detector_id():
                mechanism.append(f"D{target.val}")
            elif target.is_logical_observable_id():
                mechanism.append(f"L{target.val}")
            else:
                mechanism.append(str(target))
        probability = float(inst.args_copy()[0])
        rows.append((tuple(mechanism), probability))
    rows.sort(key=lambda item: (item[0], item[1]))
    return rows


def dem_equal(left, right) -> bool:
    if len(left) != len(right):
        return False
    for (mech_a, prob_a), (mech_b, prob_b) in zip(left, right):
        if mech_a != mech_b:
            return False
        if not math.isclose(prob_a, prob_b, rel_tol=1e-9, abs_tol=1e-15):
            return False
    return True


def detector_sample(circuit: stim.Circuit) -> list[int]:
    sample = circuit.compile_detector_sampler().sample(shots=1)
    return [int(bit) for bit in sample[0].tolist()]


def check_circuit(circuit: stim.Circuit, case_id: str) -> dict:
    started = time.perf_counter()
    broken: list[str] = []
    invariants: dict = {}
    detail = ""
    status = "pass"
    try:
        cirq_circuit = stimcirq.stim_circuit_to_cirq_circuit(circuit)
        back = stimcirq.cirq_circuit_to_stim_circuit(cirq_circuit)
        invariants["detectors"] = [circuit.num_detectors, back.num_detectors]
        invariants["observables"] = [circuit.num_observables, back.num_observables]
        if circuit.num_detectors != back.num_detectors:
            broken.append("detector_count")
        if circuit.num_observables != back.num_observables:
            broken.append("observable_count")
        original_dem = dem_rows(circuit.detector_error_model(decompose_errors=False))
        back_dem = dem_rows(back.detector_error_model(decompose_errors=False))
        invariants["dem_errors"] = [len(original_dem), len(back_dem)]
        invariants["dem_equal"] = dem_equal(original_dem, back_dem)
        if not invariants["dem_equal"]:
            broken.append("detector_error_model")
            detail = _dem_diff(original_dem, back_dem)
        noisy = has_noise(circuit)
        invariants["noise"] = noisy
        if not noisy:
            original_sample = detector_sample(circuit)
            back_sample = detector_sample(back)
            invariants["detector_sample_equal"] = original_sample == back_sample
            if original_sample != back_sample:
                broken.append("detector_sample")
                detail = f"sample {original_sample} -> {back_sample}"
        else:
            invariants["detector_sample_equal"] = None
    except Exception as exc:
        status = "error"
        detail = f"{type(exc).__name__}: {exc}"
        broken = ["exception"]
    if status != "error" and broken:
        status = "mismatch"
    return {
        "check": "stim-cirq-roundtrip",
        "case_id": case_id,
        "status": status,
        "seconds": round(time.perf_counter() - started, 6),
        "broken": broken,
        "invariants": invariants,
        "detail": detail[:800],
        "classification": None,
        "notes": [],
    }


def check_file(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return check_circuit(stim.Circuit(text), path)


def _dem_diff(left, right) -> str:
    left_set = set(left)
    right_set = set(right)
    missing = [row for row in left if row not in right_set][:3]
    extra = [row for row in right if row not in left_set][:3]
    return f"only_original={missing} only_roundtrip={extra}"
