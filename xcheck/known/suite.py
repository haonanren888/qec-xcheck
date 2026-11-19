"""One deterministic check per published defect.

PASS means the current libraries match the cited spec.
FAIL means they still disagree: that is the regression signal.
UNAVAILABLE means the saved reproduction needs a component this interpreter does not have.
"""

from __future__ import annotations

import time
from pathlib import Path

import cirq

from xcheck.known import circuits

_SPEC_INDEX = (
    "cirq/value/classical_data.py get_int: index 0 is the first measurement, "
    "-1 is the most recent. KeyCondition.resolve returns get_int(key, index) != 0."
)
_SPEC_MASK = (
    "cirq/value/condition.py BitMaskKeyCondition: (meas & bitmask) == target_value "
    "when equal_target is true. The first measured qubit is the high bit."
)
_SPEC_SYMPY = (
    "cirq/value/condition.py SympyCondition: the expression is true iff bool(x) "
    "after measurement keys are substituted. Measurement 0 substituted for m is falsy."
)
_SPEC_SWAP = (
    "cirq/value/condition.py SympyCondition.replace_key substitutes one key. "
    "A swap must keep both keys. After a↔b, b=1 > a=0, so the controlled X fires."
)
_SPEC_QASM = (
    "cirq/value/classical_data.py get_int is big-endian, so measure(q0, q1) "
    "of [1, 0] is integer 2. cirq.qasm Equality export must keep that branch."
)
_SPEC_SLICE = (
    "OpenQASM inclusive range, language/types.html#register-concatenation-and-slicing: "
    "q[3:-1:0] is the same four qubits as {3,2,1,0}."
)


def _records(circuit: cirq.Circuit) -> dict:
    result = cirq.Simulator().run(circuit)
    return {
        str(key): [[int(bit) for bit in row] for row in value[0].tolist()]
        for key, value in result.records.items()
    }


def _stim_records(circuit: cirq.Circuit) -> dict:
    import stimcirq

    result = stimcirq.StimSampler().run(circuit)
    return {
        str(key): [[int(bit) for bit in row] for row in value[0].tolist()]
        for key, value in result.records.items()
    }


def _row(check_id, url, summary, spec, expected, status, observed, seconds, watch_only=False) -> dict:
    row = {
        "id": check_id,
        "issue": url,
        "summary": summary,
        "spec": spec,
        "expected": expected,
        "status": status,
        "observed": observed,
        "seconds": round(seconds, 6),
    }
    if watch_only:
        row["watch_only"] = True
    return row


def _call(fn) -> dict:
    started = time.perf_counter()
    try:
        row = fn()
    except Exception as exc:
        return _row(
            getattr(fn, "__name__", "check"),
            "",
            "",
            "",
            "",
            "ERROR",
            f"{type(exc).__name__}: {exc}",
            time.perf_counter() - started,
        )
    row["seconds"] = round(time.perf_counter() - started, 6)
    return row


def check_8525() -> dict:
    observed = _records(circuits.circuit_8525())["out"]
    return _row(
        "cirq-8525",
        "https://github.com/quantumlib/Cirq/issues/8525",
        "KeyCondition index=0 inside a CircuitOperation must read the earliest measurement.",
        _SPEC_INDEX + " replace_key in condition.py:98-99 drops index.",
        "out == [[0]]",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_8525_mask() -> dict:
    observed = _records(circuits.circuit_8525_mask())["out"]
    return _row(
        "cirq-8525-bitmask",
        "https://github.com/quantumlib/Cirq/issues/8525",
        "BitMaskKeyCondition.replace_key must keep bitmask, target, and index.",
        _SPEC_MASK + " The integer for measurements (1, 0) is 2, and (2 & 1) == 1 is false.",
        "out == [[0]]",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_8525_json() -> dict:
    circuit = circuits.circuit_8525_json()
    restored = cirq.read_json(json_text=cirq.to_json(circuit))
    observed = _records(restored)["out"]
    return _row(
        "cirq-8525-json-index",
        "https://github.com/quantumlib/Cirq/issues/8525",
        "KeyCondition JSON must round-trip index, and index=0 stays the earliest record.",
        _SPEC_INDEX + " _from_json_dict_ in condition.py:117-119 keeps only key.",
        "out == [[0]] after JSON read-back",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_8528() -> dict:
    observed = _records(circuits.circuit_8528())["out"]
    return _row(
        "cirq-8528",
        "https://github.com/quantumlib/Cirq/issues/8528",
        "A symbol with a positive assumption must be false after substituting measurement 0.",
        _SPEC_SYMPY,
        "out == [[0]]",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_8529() -> dict:
    observed = _records(circuits.circuit_8529())["out"]
    return _row(
        "cirq-8529",
        "https://github.com/quantumlib/Cirq/issues/8529",
        "After swapping measurement keys, the condition must become b > a and the control must still fire.",
        _SPEC_SWAP,
        "out == [[1]]",
        "PASS" if observed == [[1]] else "FAIL",
        repr(observed),
        0,
    )


def check_8530() -> dict:
    from cirq.contrib.qasm_import import circuit_from_qasm

    circuit = circuits.circuit_8530()
    exported = circuit_from_qasm(cirq.qasm(circuit))
    observed = _records(exported)
    out_bits = [value for key, value in observed.items() if "out" in str(key)]
    ok = _records(circuit)["out"] == [[1]] and out_bits == [[[1]]]
    return _row(
        "cirq-8530",
        "https://github.com/quantumlib/Cirq/issues/8530",
        "After exporting a multi-bit SympyCondition to OpenQASM 2, the m==2 branch must still fire.",
        _SPEC_QASM,
        "control result stays 1 after export and import",
        "PASS" if ok else "FAIL",
        repr(observed),
        0,
    )


def check_69() -> dict:
    from qiskit.qasm3 import loads

    text = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\nx q[3:-1:0];\n'
    circuit = loads(text)
    indexes = [circuit.find_bit(bit).index for inst in circuit.data for bit in inst.qubits]
    return _row(
        "qasm3-69",
        "https://github.com/Qiskit/qiskit-qasm3-import/issues/69",
        "The inclusive descending slice q[3:-1:0] must be four X gates.",
        _SPEC_SLICE,
        "qubit indexes == [3, 2, 1, 0]",
        "PASS" if indexes == [3, 2, 1, 0] else "FAIL",
        repr(indexes),
        0,
    )


def check_1136() -> dict:
    import stimcirq

    converted = stimcirq.cirq_circuit_to_stim_circuit(circuits.circuit_1136())
    bit = int(converted.compile_sampler().sample(1)[0, -1])
    return _row(
        "stim-1136",
        "https://github.com/quantumlib/Stim/issues/1136",
        "REPEAT export must keep measurement_key_map, so the outer key b stays 0 and feedback does not fire.",
        "CircuitOperation documents that measurement_key_map renames measurement keys in the subcircuit. This row is the rename reproduction from the published issue comment, not a qubit_map invented from the title.",
        "last sampled bit == 0",
        "PASS" if bit == 0 else "FAIL",
        repr(bit),
        0,
    )


def check_1142() -> dict:
    observed = _stim_records(circuits.circuit_1142())["out"]
    return _row(
        "stim-1142",
        "https://github.com/quantumlib/Stim/issues/1142",
        "A controlled-Z with control_values=(0,) must act when the control qubit is 0.",
        "cirq/ops/controlled_gate.py ControlledGate: control_values selects the control value that enables the sub-gate; the default is 1. A plus state, then Z, then H, measures 1.",
        "out == [[1]]",
        "PASS" if observed == [[1]] else "FAIL",
        repr(observed),
        0,
    )


def check_1143() -> dict:
    observed = _stim_records(circuits.circuit_1143())["out"]
    return _row(
        "stim-1143",
        "https://github.com/quantumlib/Stim/issues/1143",
        "stimcirq must treat KeyCondition index=0 as the earliest measurement, not the latest.",
        _SPEC_INDEX,
        "out == [[0]]",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_1144() -> dict:
    try:
        observed = _stim_records(circuits.circuit_1144())["out"]
    except (NotImplementedError, ValueError) as exc:
        return _row(
            "stim-1144",
            "https://github.com/quantumlib/Stim/issues/1144",
            "Measurement confusion must not be dropped silently.",
            "Published report: an unsupported confusion map must raise, rather than turning Cirq's 0 into 1.",
            "out == [[0]], or NotImplementedError/ValueError when unsupported",
            "PASS",
            f"raised {type(exc).__name__}: {exc}",
            0,
        )
    return _row(
        "stim-1144",
        "https://github.com/quantumlib/Stim/issues/1144",
        "Measurement confusion must not be dropped silently.",
        "Published report: confusion_map turns a measured 1 into 0. The conversion must keep that result or reject the gate explicitly.",
        "out == [[0]], or NotImplementedError/ValueError when unsupported",
        "PASS" if observed == [[0]] else "FAIL",
        repr(observed),
        0,
    )


def check_1145() -> dict:
    import stimcirq

    _inner, wrapped = circuits.circuit_1145()
    converted = stimcirq.cirq_circuit_to_stim_circuit(cirq.Circuit(wrapped))
    sample = converted.compile_sampler().sample(1)[0].astype(int).tolist()
    ok = converted.num_measurements == 2 and sample == [1, 0]
    return _row(
        "stim-1145",
        "https://github.com/quantumlib/Stim/issues/1145",
        "An outer repetitions=1 must not delete the inner REPEAT.",
        "CircuitOperation.repetitions is the subcircuit repeat count. Both wrappers must leave two measurements and bits [1, 0].",
        "num_measurements == 2 and sample == [1, 0]",
        "PASS" if ok else "FAIL",
        f"num_measurements={converted.num_measurements} sample={sample}",
        0,
    )


def check_1135() -> dict:
    import stim
    import stimcirq

    text = "R 0 1 2\nTICK\nX 0\nTICK\nMPP Z0*Z1 Z2\nTICK\n"
    converted = stimcirq.stim_circuit_to_cirq_circuit(stim.Circuit(text))
    expected = {"0": [[[1]]], "1": [[[0]]]}
    try:
        result = stimcirq.StimSampler().run(converted, repetitions=1)
    except IndexError as exc:
        return _row(
            "stim-1135",
            "https://github.com/quantumlib/Stim/issues/1135",
            "Each multi-qubit Pauli measurement must produce one result bit in StimSampler.",
            "Published report: Z0*Z1=-1 and Z2=+1, with records {'0': [[[1]]], '1': [[[0]]]}. "
            "The PauliMeasurementGate branch in stimcirq/_cirq_to_stim.py writes len(targets) as the result width; "
            "a Pauli product produces one bit. _stim_sampler.py slices sample columns by that width.",
            "records == {'0': [[[1]]], '1': [[[0]]]}",
            "FAIL",
            f"IndexError: {exc}",
            0,
        )
    observed = {str(key): value.tolist() for key, value in result.records.items()}
    return _row(
        "stim-1135",
        "https://github.com/quantumlib/Stim/issues/1135",
        "Each multi-qubit Pauli measurement must produce one result bit in StimSampler.",
        "Published report: Z0*Z1=-1 and Z2=+1, with records {'0': [[[1]]], '1': [[[0]]]}. "
        "The PauliMeasurementGate branch in stimcirq/_cirq_to_stim.py writes len(targets) as the result width; "
        "a Pauli product produces one bit. _stim_sampler.py slices sample columns by that width.",
        "records == {'0': [[[1]]], '1': [[[0]]]}",
        "PASS" if observed == expected else "FAIL",
        repr(observed),
        0,
    )


def check_1137() -> dict:
    import tempfile

    import stim
    import sinter

    text = (
        "R 0 1 2\n"
        "X_ERROR(1) 0\n"
        "M 0 1 2\n"
        "DETECTOR rec[-1]\n"
        "OBSERVABLE_INCLUDE(0) rec[-3]\n"
        "OBSERVABLE_INCLUDE(1) rec[-2]\n"
    )
    task = sinter.Task(
        circuit=stim.Circuit(text),
        decoder="vacuous",
        json_metadata={"audit": "resume-error-counts"},
    )
    with tempfile.TemporaryDirectory(prefix="xcheck-1137-") as directory:
        return _check_1137_collect(task, Path(directory) / "resume.csv")


def _check_1137_collect(task, path: Path) -> dict:
    import signal

    import sinter
    from sinter._probability_util import fit_binomial

    common = dict(
        tasks=[task],
        num_workers=1,
        start_batch_size=16,
        max_batch_size=16,
        allowed_cpu_affinity_ids=[],
        save_resume_filepath=path,
    )

    def _timeout(signum, frame):
        raise TimeoutError("sinter.collect exceeded 20 seconds")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(20)
    try:
        sinter.collect(max_shots=16, count_observable_error_combos=False, **common)
        stats = sinter.collect(max_shots=32, count_observable_error_combos=True, **common)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    stat = stats[0]
    key = "obs_mistake_mask=E_"
    hits = None if key not in stat.custom_counts else int(stat.custom_counts[key])
    best = None
    if hits is not None:
        split = stat._split_custom_counts([key])[0]
        best = fit_binomial(
            num_shots=split.shots - split.discards,
            num_hits=split.errors,
            max_likelihood_factor=1e3,
        ).best
    ok = (
        stat.shots == 32
        and stat.errors == 32
        and stat.discards == 0
        and hits == 32
        and best == 1
    )
    return _row(
        "stim-1137",
        "https://github.com/quantumlib/Stim/issues/1137",
        "After resuming with observable error counts enabled, the plot numerator must cover all 32 shots.",
        "Published report: each record has observable bits 10 and prediction 00, so the component rate is 1. "
        "sinter plot's _split_custom_counts puts custom_counts into errors while shots stays the full shot count; "
        "plot_error_rate passes both to fit_binomial. Expected hits=32, shots=32, best=1.",
        "obs_mistake_mask=E_ == 32 and best == 1",
        "PASS" if ok else "FAIL",
        (
            f"shots={stat.shots} errors={stat.errors} discards={stat.discards} "
            f"{key}={hits} best={best}"
        ),
        0,
    )


def check_1132() -> dict:
    summary = "A distance-at-least-2 check must reject a distance-1 error inside a repeat block."
    spec = (
        "Published report: flat is two error(0.125) L0 lines, and repeat is "
        "repeat 2 { error(0.125) L0 }. stimflow.verify_distance_is_at_least(dem, 2) must reject both."
    )
    expected = "both flat and repeat are rejected for distance 1"
    url = "https://github.com/quantumlib/Stim/issues/1132"
    try:
        import stimflow
    except ImportError as exc:
        return _row(
            "stim-1132",
            url,
            summary,
            spec + " stimflow is not installed.",
            expected,
            "UNAVAILABLE",
            f"ImportError: {exc}",
            0,
        )
    import stim

    models = {
        "flat": "error(0.125) L0\nerror(0.125) L0\n",
        "repeat": "repeat 2 {\n    error(0.125) L0\n}\n",
    }
    lines = []
    accepted = []
    for name, text in models.items():
        dem = stim.DetectorErrorModel(text)
        try:
            stimflow.verify_distance_is_at_least(dem, 2)
        except ValueError as error:
            lines.append(f"{name} rejected: {error}")
        else:
            accepted.append(name)
            lines.append(f"{name} ACCEPTED")
    return _row(
        "stim-1132",
        url,
        summary,
        spec,
        expected,
        "PASS" if accepted == [] and len(lines) == 2 else "FAIL",
        "; ".join(lines),
        0,
    )


def _likelihood_gap(p, n, k, factor, ph):
    import math

    return (
        k * math.log(p / ph)
        + (n - k) * (math.log1p(-p) - math.log1p(-ph))
        + math.log(factor)
    )


def _exact_low(n, k, factor):
    """Log-space bisection. A negative gap is outside the interval. Return the smallest p that still meets the likelihood ratio."""
    ph = k / n
    lo = 1e-30
    for _ in range(20):
        if _likelihood_gap(lo, n, k, factor, ph) < 0:
            break
        lo /= 100
    else:
        raise RuntimeError("low bracket failed")
    hi = ph
    for _ in range(200):
        mid = (lo * hi) ** 0.5
        if _likelihood_gap(mid, n, k, factor, ph) < 0:
            lo = mid
        else:
            hi = mid
    return hi


def _exact_high(n, k, factor):
    """Upper bisection of the same gap. Return the largest p that still meets the likelihood ratio."""
    ph = k / n
    lo = ph
    hi = min(1.0 - 1e-15, ph + 0.001)
    for _ in range(20):
        if hi < 1 and _likelihood_gap(hi, n, k, factor, ph) < 0:
            break
        hi = min(1.0 - 1e-15, ph + (hi - ph) * 10)
    else:
        raise RuntimeError("high bracket failed")
    for _ in range(80):
        mid = (lo + hi) / 2
        if _likelihood_gap(mid, n, k, factor, ph) > 0:
            lo = mid
        else:
            hi = mid
    return hi


def _ratio_status(ratio, fail_above, pass_at):
    if ratio != ratio or ratio in (float("inf"), float("-inf")):
        return "ERROR"
    if ratio > fail_above:
        return "FAIL"
    if ratio <= pass_at:
        return "PASS"
    return "ERROR"


def check_1146_grid() -> dict:
    try:
        import sinter
    except ImportError as exc:
        return _row(
            "stim-1146-grid",
            "https://github.com/quantumlib/Stim/issues/1146",
            "With one hit, the fit_binomial lower edge must not sit more than twice the exact likelihood-ratio lower edge.",
            "Published report: n=10^6, hits=1, F=1000. This interpreter has no sinter.",
            "sinter.low / exact_low <= 1.05",
            "UNAVAILABLE",
            f"ImportError: {exc}",
            0,
        )

    n, k, factor = 10**6, 1, 1000
    exact = _exact_low(n, k, factor)
    got = sinter.fit_binomial(num_shots=n, num_hits=k, max_likelihood_factor=factor)
    ratio = float(got.low) / exact
    return _row(
        "stim-1146-grid",
        "https://github.com/quantumlib/Stim/issues/1146",
        "With one hit, the fit_binomial lower edge must not sit more than twice the exact likelihood-ratio lower edge.",
        "Published report: n=10^6, hits=1, F=1000; the exact lower edge is about 1/(e*F*n). "
        "Sinter's acc=100 grid lifts the lower edge to 0.01/n. A ratio above 2 is FAIL; a ratio of at most 1.05 is PASS.",
        "sinter.low / exact_low <= 1.05",
        _ratio_status(ratio, fail_above=2, pass_at=1.05),
        f"low={got.low} exact={exact:.6e} ratio={ratio:.6g}",
        0,
    )


def check_1146_float32() -> dict:
    try:
        import sinter
    except ImportError as exc:
        return _row(
            "stim-1146-float32",
            "https://github.com/quantumlib/Stim/issues/1146",
            "On a large sample, a float32 log-likelihood must not stretch the upper half-width past 1.05 times the exact half-width.",
            "Published report: n=10^9, hits=10^8, F=1000. This interpreter has no sinter.",
            "(sinter.high - hits/n) / (exact_high - hits/n) <= 1.05",
            "UNAVAILABLE",
            f"ImportError: {exc}",
            0,
        )

    n, k, factor = 10**9, 10**8, 1000
    ph = k / n
    exact = _exact_high(n, k, factor)
    got = sinter.fit_binomial(num_shots=n, num_hits=k, max_likelihood_factor=factor)
    ratio = (float(got.high) - ph) / (exact - ph)
    return _row(
        "stim-1146-float32",
        "https://github.com/quantumlib/Stim/issues/1146",
        "On a large sample, a float32 log-likelihood must not stretch the upper half-width past 1.05 times the exact half-width.",
        "Published report: n=10^9, hits=10^8, F=1000; the upper half-width is about 1.50 times the exact half-width. "
        "A half-width ratio above 1.05 is FAIL; a ratio of at most 1.05 is PASS.",
        "(sinter.high - hits/n) / (exact_high - hits/n) <= 1.05",
        _ratio_status(ratio, fail_above=1.05, pass_at=1.05),
        f"high={got.high} exact={exact:.8f} half_ratio={ratio:.6g}",
        0,
    )


def prediction_matches_observable(predicted, observable) -> str:
    """Return ``match``, ``mismatch``, or ``invalid``.

    A wrong shape or a value outside {0, 1} is ``invalid``. That result
    is not treated as a match by dropping extra columns.
    """
    import numpy as np

    got = np.asarray(predicted)
    expect = np.asarray(observable)
    if got.shape != expect.shape:
        return "invalid"
    try:
        bits = np.logical_or(np.equal(got, 0), np.equal(got, 1))
        if not bool(np.all(bits)):
            return "invalid"
    except Exception:
        return "invalid"
    if np.array_equal(got.astype(np.uint8), expect.astype(np.uint8)):
        return "match"
    return "mismatch"


def check_pymatching_193() -> dict:
    summary = (
        "On distance-3 rotated memory Z, correlated matching must correct every single fault. "
        "This row is watch-only: it records the result and does not draft a comment."
    )
    spec = (
        "Recorded positive control for PyMatching #193: surface_code:rotated_memory_z, "
        "distance=3, rounds=3, after_clifford_depolarization=0.001, "
        "detector_error_model(decompose_errors=True), enable_correlations=True. "
        "A single-fault failure count above 0 is FAIL."
    )
    expected = "single-fault failure count == 0"
    url = "https://github.com/oscarhiggott/PyMatching/issues/193"
    try:
        import numpy as np
        import pymatching
        import stim
    except ImportError as exc:
        return _row(
            "pymatching-193-d3",
            url,
            summary,
            spec,
            expected,
            "UNAVAILABLE",
            f"ImportError: {exc}",
            0,
            watch_only=True,
        )
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
    )
    dem = circuit.detector_error_model(decompose_errors=True)
    if int(dem.num_observables) != 1:
        return _row(
            "pymatching-193-d3",
            url,
            summary,
            spec,
            expected,
            "ERROR",
            f"expected 1 observable, got {int(dem.num_observables)}",
            0,
            watch_only=True,
        )
    matcher = pymatching.Matching.from_detector_error_model(dem, enable_correlations=True)
    bad = 0
    total = 0
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        total += 1
        syndrome = np.zeros(dem.num_detectors, np.uint8)
        observable = np.zeros(1, np.uint8)
        for target in inst.targets_copy():
            if target.is_relative_detector_id():
                syndrome[target.val] ^= 1
            elif target.is_logical_observable_id():
                observable[0] ^= 1
        predicted = np.asarray(matcher.decode(syndrome, enable_correlations=True))
        kind = prediction_matches_observable(predicted, observable)
        if kind == "invalid":
            return _row(
                "pymatching-193-d3",
                url,
                summary,
                spec,
                expected,
                "ERROR",
                (
                    "decoder output shape "
                    f"{tuple(predicted.shape)} is not {tuple(observable.shape)} "
                    "or a value is outside 0 and 1"
                ),
                0,
                watch_only=True,
            )
        if kind == "mismatch":
            bad += 1
    return _row(
        "pymatching-193-d3",
        url,
        summary,
        spec,
        expected,
        "PASS" if bad == 0 else "FAIL",
        f"single_fault_failures={bad} total={total}",
        0,
        watch_only=True,
    )


def all_checks() -> list:
    ran = [
        check_8525,
        check_8525_mask,
        check_8525_json,
        check_8528,
        check_8529,
        check_8530,
        check_69,
        check_1136,
        check_1142,
        check_1143,
        check_1144,
        check_1145,
        check_1135,
        check_1137,
        check_1132,
        check_1146_grid,
        check_1146_float32,
        check_pymatching_193,
    ]
    return [_call(fn) for fn in ran]


def _table(rows: list[dict]) -> str:
    lines = [
        "| id | status | issue | summary | expected | observed | mark |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        mark = "watch_only" if row.get("watch_only") else ""
        lines.append(
            "| {id} | {status} | {issue} | {summary} | {expected} | {observed} | {mark} |".format(
                mark=mark, **row
            )
        )
    return "\n".join(lines)


def run_known() -> dict:
    rows = all_checks()
    counts = {"PASS": 0, "FAIL": 0, "UNAVAILABLE": 0, "ERROR": 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    if counts["ERROR"]:
        exit_code = 2
    elif counts["FAIL"]:
        exit_code = 1
    else:
        exit_code = 0
    return {
        "check": "known",
        "counts": counts,
        "watch_only": [row["id"] for row in rows if row.get("watch_only")],
        "exit_code": exit_code,
        "cases": rows,
        "table": _table(rows),
    }


def oracle_8525() -> dict:
    from xcheck.cirq_control import check_circuit

    circuit = circuits.circuit_8525()
    plain = check_circuit(circuit, "builtin:8525", use_oracle=False)
    oracle = check_circuit(circuit, "builtin:8525", use_oracle=True)
    return {
        "case": "builtin:8525",
        "without_oracle": plain["status"],
        "with_oracle": oracle["status"],
        "without_broken": plain["broken"],
        "with_broken": oracle["broken"],
        "oracle_bits": oracle["invariants"].get("oracle"),
        "direct_bits": oracle["invariants"].get("direct"),
    }
