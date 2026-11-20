"""DEM fault check for one decoder on one Stim circuit.

A fault is one detector-error-model ``error`` instruction after
``decompose_errors=True``. One correlated fault counts as 1. The ``^``
separator splits that instruction into edges; the syndrome and the
observable are the parity of every target. Faults are not counted by
decomposed graph edges. A weight-2 case is an unordered pair of those
faults, combined by parity. This is not an injection of two circuit
Pauli errors.

The distance figure is a Stim search result (upper bound from the stated
search). It is the shorter positive length among ``shortest_graphlike_error``
and ``search_for_undetectable_logical_errors``.

Statuses and process exit codes:

- ``COUNTEREXAMPLE`` — exit 1, with at least one counterexample DEM text
- ``EXHAUSTIVE_NONE`` — exit 0, the stated weight range was fully enumerated
- ``SAMPLED_NONE`` — exit 3, a sample found no counterexample (``not a guarantee``)
- ``UNAVAILABLE`` — exit 4, the check could not be evaluated
- ``TIMEOUT`` — exit 4, ``--timeout`` stopped the check and no counterexample had been found yet
- ``DECODER_OUTPUT_INVALID`` — exit 2, ``decode_batch`` broke its contract
- usage errors — exit 2

A derived cutoff of 0 (the Stim search result is below 3, and neither
``--max-weight`` nor ``--sample-pairs`` was set) is ``UNAVAILABLE``. The
message says that 0 faults were tested and names ``--max-weight 1``. It
does not use the no-counterexample scope sentence.

``--timeout`` stops the enumeration. A counterexample already found stays
``COUNTEREXAMPLE`` (exit 1). Otherwise the status is ``TIMEOUT``.

A counterexample found at any enumerated weight stays ``COUNTEREXAMPLE``.
If a later weight is not run because of the pair budget, the output notes
``weight 2: not enumerated (0 pairs checked, reason ...)`` and does not
change the status to ``UNAVAILABLE``. The counterexample lines stay.

Weight-2 enumeration counts pairs first. Above the default limit of
2,000,000 pairs, and without ``--sample-pairs``, those pairs are not
enumerated. If no counterexample was found at a lower weight, the command
returns ``UNAVAILABLE``. The message includes the pair count, a time
estimate scaled from a local decoder timing, and suggested
``--sample-pairs`` and ``--max-pairs`` commands. ``--max-pairs`` raises
that limit.

``decode_batch`` must return a two-dimensional array with one row per
input sample, one column per DEM observable, and values in {0, 1} only.
Any other rank, shape, value, ``None``, or exception is
``DECODER_OUTPUT_INVALID``. The check does not truncate, broadcast, or
pad that array.

``--sample-pairs`` returns only ``SAMPLED_NONE`` or ``COUNTEREXAMPLE``.

Each counterexample is decoded again with ordinary PyMatching on the same
DEM. The label is ``DECODER_SPECIFIC`` when that reference predicts the
observable, ``REFERENCE_ALSO_FAILS`` when it does not, and
``REFERENCE_UNAVAILABLE`` when it cannot be run. Those labels do not
change the exit code. ``REFERENCE_ALSO_FAILS`` adds a hint that the
enumerated cutoff may sit past the true correction radius, because the
Stim search result is an upper bound.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

for _thread_key in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMBA_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_thread_key, "1")

_EXAMPLE_LIMIT = 8
_PAIR_CHUNK = 50000
DEFAULT_MAX_PAIRS = 2_000_000
_SAMPLE_TARGET_SECONDS = 30.0
_DECODERS = ("pymatching", "pymatching-correlated", "tesseract", "toy-broken")
DISTANCE_LABEL = "Stim search result (upper bound from the stated search)"
SCOPE_PHRASE = (
    "no counterexample found within the stated scope "
    "(versions, noise model, enumerated weights)"
)
NOT_A_GUARANTEE = "not a guarantee"
FAULT_UNIT = (
    "One fault is one DEM error mechanism (one error instruction). "
    "One correlated fault counts as 1. "
    "Faults are not counted by decomposed graph edges."
)
_DECOMPOSITION_METHOD = "detector_error_model(decompose_errors=True)"
_CUTOFF_STATEMENT = (
    "The enumerated cutoff is floor((Stim search result - 1) / 2), capped at 2. "
    "That cutoff uses the Stim search result, which is an upper bound from the stated search."
)
_NOISE_STATEMENT = (
    "The noise model is taken from the circuit. This command does not add a noise channel."
)
REFERENCE_ALSO_FAILS_HINT = (
    "The truncation may exceed the true correction radius "
    "(the Stim search result is an upper bound)."
)
_ATTRIBUTION_KEYS = (
    "DECODER_SPECIFIC",
    "REFERENCE_ALSO_FAILS",
    "REFERENCE_UNAVAILABLE",
)


class _TimedOut(Exception):
    """The ``--timeout`` budget ended before this call returned."""


class _FactoryUnavailable(Exception):
    """A custom factory could not be imported or constructed."""


class _Deadline:
    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self.started = time.perf_counter()

    def expired(self) -> bool:
        return (time.perf_counter() - self.started) >= self.seconds

    def remaining(self) -> float:
        return self.seconds - (time.perf_counter() - self.started)


def _call_within(deadline: _Deadline | None, fn, *args):
    """Run ``fn`` on this thread, or stop waiting when ``deadline`` expires.

    The worker is a daemon so a decoder that is still running after the budget
    does not hold the process open. No process is killed.
    """
    if deadline is None:
        return fn(*args)
    remaining = deadline.remaining()
    if remaining <= 0:
        raise _TimedOut()
    box: dict = {}

    def _run():
        try:
            box["value"] = fn(*args)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(remaining)
    if thread.is_alive():
        raise _TimedOut()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _custom_import_message(module_name: str, exc: BaseException) -> str:
    detail = f"{type(exc).__name__}: {_short(exc)}"
    if sys.flags.isolated:
        why = (
            "python -I drops PYTHONPATH and does not add the working directory "
            "to sys.path. Insert the directory that contains the module into "
            "sys.path before starting."
        )
    else:
        why = (
            "This interpreter is not in isolated mode (python -I). "
            "The module was not found on sys.path."
        )
    return f"{detail}. custom module {module_name} failed to import. {why}"


def _import_numpy():
    import numpy

    return numpy


def _import_stim():
    import stim

    return stim


def _import_pymatching():
    import pymatching

    return pymatching


def _import_tesseract():
    import tesseract_decoder

    return tesseract_decoder


def ranks_to_pairs(k, n: int):
    """Map combination ranks to unordered pairs ``(i, j)`` with ``i < j``."""
    np = _import_numpy()
    k = np.asarray(k, dtype=np.int64)
    disc = ((2 * n - 1) ** 2 - 8 * k).astype(np.float64)
    i = np.floor(((2 * n - 1) - np.sqrt(np.maximum(disc, 0.0))) / 2.0).astype(np.int64)
    i = np.clip(i, 0, max(n - 2, 0))
    start = i * (2 * n - i - 1) // 2
    i = i - (start > k).astype(np.int64)
    start = i * (2 * n - i - 1) // 2
    nxt = (i + 1) * (2 * n - (i + 1) - 1) // 2
    i = i + ((nxt <= k) & (i + 1 <= n - 2)).astype(np.int64)
    start = i * (2 * n - i - 1) // 2
    j = i + 1 + (k - start)
    return i, j


def _sample_ranks(total: int, want: int):
    np = _import_numpy()
    if want >= total:
        return np.arange(total, dtype=np.int64)
    pos = np.linspace(0, total - 1, want)
    return np.unique(np.rint(pos).astype(np.int64))


def _search_params(graphlike_weight: int | None) -> dict:
    wide = graphlike_weight is not None and graphlike_weight <= 3
    if wide:
        return {
            "dont_explore_detection_event_sets_with_size_above": 8,
            "dont_explore_edges_with_degree_above": 6,
            "dont_explore_edges_increasing_symptom_degree": False,
            "canonicalize_circuit_errors": True,
        }
    return {
        "dont_explore_detection_event_sets_with_size_above": 6,
        "dont_explore_edges_with_degree_above": 4,
        "dont_explore_edges_increasing_symptom_degree": True,
        "canonicalize_circuit_errors": True,
    }


def _short(text: str, limit: int = 2000) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _library_versions(decoder: str | None = None) -> dict:
    import xcheck

    versions = {"xcheck": xcheck.__version__}
    for key, importer in (
        ("stim", _import_stim),
        ("numpy", _import_numpy),
        ("pymatching", _import_pymatching),
    ):
        try:
            module = importer()
        except ImportError:
            continue
        versions[key] = str(getattr(module, "__version__", "unknown"))
    if decoder == "tesseract":
        try:
            module = _import_tesseract()
        except ImportError:
            pass
        else:
            versions["tesseract_decoder"] = str(getattr(module, "__version__", "unknown"))
    return versions


def _noise_model(circuit) -> dict:
    counts: dict[str, int] = {}
    for inst in circuit.flattened():
        name = inst.name
        if "ERROR" in name or "DEPOLARIZE" in name or "PAULI_CHANNEL" in name:
            counts[name] = counts.get(name, 0) + 1
    return {
        "source": "circuit",
        "statement": _NOISE_STATEMENT,
        "instruction_counts": counts,
    }


def measure_distance(circuit) -> dict:
    """Stim search lengths. The numeric result is an upper bound from this search."""
    out: dict = {
        "label": DISTANCE_LABEL,
        "stim_search_result": None,
        "graphlike_weight": None,
        "graphlike_error": None,
        "search_weight": None,
        "search_error": None,
        "search_params": None,
    }
    try:
        graph = circuit.shortest_graphlike_error(canonicalize_circuit_errors=True)
        out["graphlike_weight"] = int(len(graph))
    except Exception as exc:
        out["graphlike_error"] = f"{type(exc).__name__}: {_short(exc)}"
    params = _search_params(out["graphlike_weight"])
    out["search_params"] = params
    try:
        found = circuit.search_for_undetectable_logical_errors(**params)
        out["search_weight"] = int(len(found))
    except Exception as exc:
        out["search_error"] = f"{type(exc).__name__}: {_short(exc)}"
    weights = [
        value
        for value in (out["graphlike_weight"], out["search_weight"])
        if isinstance(value, int) and value > 0
    ]
    if not weights:
        out["search_failure"] = "Stim did not return a logical-error length"
        return out
    out["stim_search_result"] = int(min(weights))
    out["search_failure"] = None
    return out


def extract_faults(dem) -> dict:
    np = _import_numpy()
    syndromes = []
    observables = []
    texts = []
    n_det = int(dem.num_detectors)
    n_obs = int(dem.num_observables)
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        syndrome = np.zeros(n_det, dtype=np.uint8)
        observable = np.zeros(n_obs, dtype=np.uint8)
        for target in inst.targets_copy():
            if target.is_relative_detector_id():
                syndrome[target.val] ^= 1
            elif target.is_logical_observable_id():
                observable[target.val] ^= 1
        syndromes.append(syndrome)
        observables.append(observable)
        texts.append(_short(str(inst), 2000))
    if syndromes:
        stacked_s = np.stack(syndromes)
        stacked_o = np.stack(observables)
    else:
        stacked_s = np.zeros((0, n_det), dtype=np.uint8)
        stacked_o = np.zeros((0, n_obs), dtype=np.uint8)
    return {
        "syndromes": stacked_s,
        "observables": stacked_o,
        "texts": texts,
        "n_detectors": n_det,
        "n_observables": n_obs,
    }


class DecoderOutputInvalid(Exception):
    """``decode_batch`` returned a value this check will not interpret."""

    def __init__(self, expected, actual, detail: str):
        self.expected = expected
        self.actual = actual
        self.detail = detail
        super().__init__(detail)


def _require_decoder_output(predicted, n_rows: int, n_obs: int):
    """Accept only shape ``(n_rows, n_obs)`` with values 0 or 1.

    Do not truncate, broadcast, or fill a wrong array with zeros.
    """
    np = _import_numpy()
    expected = (int(n_rows), int(n_obs))
    if predicted is None:
        raise DecoderOutputInvalid(expected, None, f"expected {expected} got None")
    try:
        arr = np.asarray(predicted)
    except Exception as exc:
        raise DecoderOutputInvalid(
            expected,
            None,
            f"expected {expected} got exception {type(exc).__name__}: {_short(exc)}",
        ) from None
    actual = tuple(int(value) for value in arr.shape)
    if arr.ndim != 2 or actual != expected:
        raise DecoderOutputInvalid(expected, actual, f"expected {expected} got {actual}")
    try:
        bits = np.logical_or(np.equal(arr, 0), np.equal(arr, 1))
        all_bits = bool(np.all(bits))
    except Exception:
        all_bits = False
    if not all_bits:
        raise DecoderOutputInvalid(
            expected,
            actual,
            f"expected {expected} got {actual}; values must be 0 or 1",
        )
    return np.array(arr, dtype=np.uint8, copy=True)


def _call_decode(decode_batch, syndromes, n_obs: int):
    np = _import_numpy()
    syndromes = np.ascontiguousarray(syndromes, dtype=np.uint8)
    if syndromes.ndim == 1:
        syndromes = syndromes.reshape(1, -1)
    n_rows = int(syndromes.shape[0])
    if n_rows == 0:
        return np.zeros((0, int(n_obs)), dtype=np.uint8)
    try:
        predicted = decode_batch(syndromes)
    except _CorrelatedUnsupported:
        raise
    except Exception as exc:
        raise DecoderOutputInvalid(
            (n_rows, int(n_obs)),
            None,
            (
                f"expected ({n_rows}, {int(n_obs)}) got exception "
                f"{type(exc).__name__}: {_short(exc)}"
            ),
        ) from None
    return _require_decoder_output(predicted, n_rows, n_obs)


def _mismatch(predicted, true_obs):
    np = _import_numpy()
    true_obs = np.asarray(true_obs, dtype=np.uint8)
    checked = _require_decoder_output(
        predicted, int(true_obs.shape[0]), int(true_obs.shape[1])
    )
    return np.any(checked != true_obs, axis=1)


def custom_spec_error(spec: str) -> str | None:
    if not spec.startswith("custom:"):
        return None
    body = spec[len("custom:") :]
    module_name, separator, function_name = body.rpartition(":")
    if (
        separator != ":"
        or not module_name
        or "/" in body
        or "\\" in body
        or not function_name.isidentifier()
    ):
        return "custom decoder must look like custom:module:function"
    return None


def _load_custom(spec: str):
    problem = custom_spec_error(spec)
    if problem:
        raise ValueError(problem)
    module_name, _, function_name = spec[len("custom:") :].rpartition(":")
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name)
    if not callable(factory):
        raise TypeError(f"{function_name} is not callable")
    return factory


def _as_decode_batch(factory_result):
    if hasattr(factory_result, "decode_batch"):
        decode_batch = factory_result.decode_batch
        if not callable(decode_batch):
            raise TypeError("decode_batch is not callable")
        return decode_batch
    if callable(factory_result):
        return factory_result
    raise TypeError("custom factory must return an object with decode_batch(dets)")


def _pymatching_batch(matcher, dem):
    def decode_batch(syndromes, _matcher=matcher):
        if getattr(syndromes, "size", 1) == 0:
            np = _import_numpy()
            return np.zeros((0, dem.num_observables), dtype=np.uint8)
        return _matcher.decode_batch(syndromes)

    return decode_batch


class _CorrelatedUnsupported(Exception):
    def __init__(self, version: str, kind: str):
        self.version = version
        self.kind = kind
        super().__init__(kind)


def _correlated_unavailable(version: str, kind: str) -> str:
    return (
        "UNAVAILABLE: pymatching "
        f"{version} does not provide enable_correlations ({kind}). "
        "Correlated matching needs enable_correlations=True when the matcher "
        "is built and when it decodes."
    )


def _suggested_sample_size(pair_space: int, seconds_per_row: float) -> int:
    if pair_space < 1:
        return 1
    if seconds_per_row <= 0:
        return min(10_000, pair_space)
    guess = int(_SAMPLE_TARGET_SECONDS / seconds_per_row)
    if guess < 1:
        guess = 1
    if guess > pair_space:
        guess = pair_space
    return guess


def load_decoder(name: str, dem):
    """Return ``(decode_batch, None)`` or ``(None, unavailable_message)``."""
    if name == "pymatching":
        try:
            pymatching = _import_pymatching()
            _import_numpy()
        except ImportError:
            return None, "UNAVAILABLE: pymatching or numpy is not installed"
        matcher = pymatching.Matching.from_detector_error_model(dem)
        return _pymatching_batch(matcher, dem), None
    if name == "pymatching-correlated":
        try:
            pymatching = _import_pymatching()
            _import_numpy()
        except ImportError:
            return None, "UNAVAILABLE: pymatching or numpy is not installed"
        version = str(getattr(pymatching, "__version__", "unknown"))
        try:
            matcher = pymatching.Matching.from_detector_error_model(
                dem, enable_correlations=True
            )
        except (TypeError, AttributeError) as exc:
            return None, _correlated_unavailable(version, type(exc).__name__)

        def decode_batch(syndromes, _matcher=matcher, _version=version):
            if getattr(syndromes, "size", 1) == 0:
                np = _import_numpy()
                return np.zeros((0, dem.num_observables), dtype=np.uint8)
            try:
                return _matcher.decode_batch(syndromes, enable_correlations=True)
            except (TypeError, AttributeError) as exc:
                raise _CorrelatedUnsupported(_version, type(exc).__name__) from None

        return decode_batch, None
    if name == "toy-broken":
        try:
            pymatching = _import_pymatching()
            np = _import_numpy()
        except ImportError:
            return None, "UNAVAILABLE: pymatching or numpy is not installed"
        faults = extract_faults(dem)
        n_obs = int(faults["n_observables"])
        n_faults = int(faults["syndromes"].shape[0])
        if n_faults < 1 or n_obs < 1:
            return None, (
                "UNAVAILABLE: toy-broken needs one DEM error mechanism and one observable"
            )
        planted = 0
        target = np.array(faults["syndromes"][planted], copy=True)
        wrong = np.array(faults["observables"][planted], copy=True)
        wrong[0] = np.uint8(int(wrong[0]) ^ 1)
        matcher = pymatching.Matching.from_detector_error_model(dem)

        def decode_batch(
            syndromes,
            _matcher=matcher,
            _target=target,
            _wrong=wrong,
            _n_obs=n_obs,
        ):
            np = _import_numpy()
            syndromes = np.asarray(syndromes, dtype=np.uint8)
            if syndromes.size == 0:
                return np.zeros((0, _n_obs), dtype=np.uint8)
            if syndromes.ndim == 1:
                syndromes = syndromes.reshape(1, -1)
            raw = np.asarray(_matcher.decode_batch(syndromes))
            if raw.ndim == 1:
                raw = raw.reshape(-1, 1)
            got = np.zeros((syndromes.shape[0], _n_obs), dtype=np.uint8)
            if raw.shape[0] == syndromes.shape[0] and raw.ndim == 2 and raw.shape[1] > 0:
                copy = min(_n_obs, int(raw.shape[1]))
                got[:, :copy] = np.asarray(raw[:, :copy], dtype=np.uint8) & np.uint8(1)
            match = np.all(syndromes == _target.reshape(1, -1), axis=1)
            got[match] = _wrong
            return got

        decode_batch.planted_fault_index = planted
        return decode_batch, None
    if name == "tesseract":
        try:
            tesseract_decoder = _import_tesseract()
            _import_numpy()
        except ImportError:
            return None, "UNAVAILABLE: tesseract_decoder or numpy is not installed"
        config = tesseract_decoder.tesseract.TesseractConfig()
        config.dem = dem
        decoder = tesseract_decoder.tesseract.TesseractDecoder(config)

        def decode_batch(syndromes, _decoder=decoder):
            np = _import_numpy()
            syndromes = np.asarray(syndromes)
            if syndromes.size == 0:
                return np.zeros((0, dem.num_observables), dtype=np.uint8)
            predicted = _decoder.decode_batch(np.ascontiguousarray(syndromes.astype(bool)))
            return np.asarray(predicted, dtype=np.uint8)

        return decode_batch, None
    if name.startswith("custom:"):
        try:
            _import_numpy()
        except ImportError:
            return None, "UNAVAILABLE: numpy is not installed"
        problem = custom_spec_error(name)
        if problem:
            raise ValueError(problem)
        module_name, _, function_name = name[len("custom:") :].rpartition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise _FactoryUnavailable(_custom_import_message(module_name, exc)) from None
        try:
            factory = getattr(module, function_name)
            if not callable(factory):
                raise TypeError(f"{function_name} is not callable")
            return _as_decode_batch(factory(dem)), None
        except Exception as exc:
            raise _FactoryUnavailable(f"{type(exc).__name__}: {_short(exc)}") from None
    raise ValueError(f"unknown decoder {name}")


def _empty_attribution() -> dict:
    return {key: 0 for key in _ATTRIBUTION_KEYS}


def _load_reference(decoder_name: str, dem, tested_decode):
    """Ordinary PyMatching on the same DEM. ``(decode_batch, error)``."""
    if decoder_name == "pymatching":
        return tested_decode, None
    try:
        pymatching = _import_pymatching()
        _import_numpy()
    except ImportError:
        return None, "pymatching or numpy is not installed"
    try:
        matcher = pymatching.Matching.from_detector_error_model(dem)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {_short(exc)}"
    return _pymatching_batch(matcher, dem), None


def _attribute_failures(reference, syndromes, true_obs, fail_mask, counts: dict, examples: list, make_item) -> int:
    """Classify every failed row. Store at most the remaining example slots."""
    np = _import_numpy()
    failed = np.flatnonzero(np.asarray(fail_mask))
    n_failed = int(failed.shape[0])
    if n_failed == 0:
        return 0
    labels = ["REFERENCE_UNAVAILABLE"] * n_failed
    if reference is not None:
        try:
            predicted = _call_decode(
                reference, syndromes[failed], int(true_obs.shape[1])
            )
            ref_bad = _mismatch(predicted, true_obs[failed])
            labels = [
                "REFERENCE_ALSO_FAILS" if bool(flag) else "DECODER_SPECIFIC"
                for flag in np.asarray(ref_bad).tolist()
            ]
        except Exception:
            labels = ["REFERENCE_UNAVAILABLE"] * n_failed
    for offset, index in enumerate(failed.tolist()):
        label = labels[offset]
        counts[label] += 1
        if len(examples) < _EXAMPLE_LIMIT:
            item = make_item(int(index))
            item["attribution"] = label
            examples.append(item)
    return n_failed


def _check_pairs(
    decode_batch,
    faults: dict,
    sample_pairs: int | None,
    examples: list,
    counts: dict,
    reference,
    deadline: _Deadline | None = None,
) -> dict:
    np = _import_numpy()
    syndromes = faults["syndromes"]
    observables = faults["observables"]
    texts = faults["texts"]
    n = int(syndromes.shape[0])
    total = n * (n - 1) // 2

    def _decode(block):
        if deadline is not None and deadline.expired():
            raise _TimedOut()
        return _call_within(
            deadline,
            _call_decode,
            decode_batch,
            block,
            int(faults["n_observables"]),
        )

    if n < 2 or total == 0:
        return {"pair_space": total, "pairs_tested": 0, "pair_failures": 0, "exhaustive": True}
    if sample_pairs is None or sample_pairs >= total:
        tested = 0
        failures = 0
        for left in range(n - 1):
            syndrome = np.bitwise_xor(syndromes[left + 1 :], syndromes[left])
            true_obs = np.bitwise_xor(observables[left + 1 :], observables[left])
            for start in range(0, syndrome.shape[0], _PAIR_CHUNK):
                stop = min(start + _PAIR_CHUNK, syndrome.shape[0])
                predicted = _decode(syndrome[start:stop])
                mask = _mismatch(predicted, true_obs[start:stop])
                failures += _attribute_failures(
                    reference,
                    syndrome[start:stop],
                    true_obs[start:stop],
                    mask,
                    counts,
                    examples,
                    lambda rel, left=left, start=start: {
                        "weight": 2,
                        "i": left,
                        "j": left + 1 + start + rel,
                        "dem": (
                            texts[left]
                            + "\n"
                            + texts[left + 1 + start + rel]
                        ),
                    },
                )
                tested += stop - start
        return {
            "pair_space": total,
            "pairs_tested": tested,
            "pair_failures": failures,
            "exhaustive": tested == total,
        }
    ranks = _sample_ranks(total, sample_pairs)
    left, right = ranks_to_pairs(ranks, n)
    failures = 0
    tested = 0
    for start in range(0, len(left), _PAIR_CHUNK):
        stop = min(start + _PAIR_CHUNK, len(left))
        syndrome = np.bitwise_xor(syndromes[left[start:stop]], syndromes[right[start:stop]])
        true_obs = np.bitwise_xor(observables[left[start:stop]], observables[right[start:stop]])
        predicted = _decode(syndrome)
        mask = _mismatch(predicted, true_obs)

        def _item(rel, start=start, left=left, right=right):
            i = int(left[start + rel])
            j = int(right[start + rel])
            return {
                "weight": 2,
                "i": i,
                "j": j,
                "dem": texts[i] + "\n" + texts[j],
            }

        failures += _attribute_failures(
            reference,
            syndrome,
            true_obs,
            mask,
            counts,
            examples,
            _item,
        )
        tested += stop - start
    return {
        "pair_space": total,
        "pairs_tested": tested,
        "pair_failures": failures,
        "exhaustive": False,
    }


def _stated_scope(
    decoder: str,
    noise: dict | None,
    distance: dict | None,
    observable_count: int | None,
    fault_count: int | None,
    checked: int | None,
    correctable: int | None,
    sampling_ratio: str | None,
) -> dict:
    scope = {
        "versions": _library_versions(decoder),
        "noise_model": noise,
        "decomposition": {
            "method": _DECOMPOSITION_METHOD,
            "fault_unit": FAULT_UNIT,
            "syndrome": "parity of all detector targets on that error instruction",
            "observable": "parity of all logical-observable targets on that error instruction",
        },
        "observable_count": observable_count,
        "fault_count": fault_count,
        "distance": distance,
        "enumerated_max_weight": checked,
        "correctable_weight_from_search": correctable,
        "cutoff_statement": _CUTOFF_STATEMENT,
        "sampling_ratio": sampling_ratio,
    }
    return scope


def _timeout_message(seconds: float) -> str:
    return (
        f"TIMEOUT: stopped after {seconds:g}s before the stated weights were fully enumerated"
    )


def run_check(
    circuit_label: str,
    circuit,
    decoder: str,
    max_weight: int | None = None,
    sample_pairs: int | None = None,
    max_pairs: int | None = None,
    timeout: float | None = None,
) -> dict:
    if max_weight is not None and int(max_weight) not in (1, 2):
        return _usage(decoder, circuit_label, "max-weight must be 1 or 2")
    try:
        stim = _import_stim()
        _import_numpy()
    except ImportError:
        return _unavailable(decoder, "UNAVAILABLE: stim or numpy is not installed", circuit_label)
    if not isinstance(circuit, stim.Circuit):
        raise TypeError("circuit must be a stim.Circuit")
    noise = _noise_model(circuit)
    try:
        dem = circuit.detector_error_model(decompose_errors=True)
    except Exception as exc:
        payload = _unavailable(
            decoder,
            f"UNAVAILABLE: {type(exc).__name__}: {_short(exc)}",
            circuit_label,
        )
        payload["stated_scope"] = _stated_scope(
            decoder, noise, None, None, None, None, None, None
        )
        return payload
    if int(dem.num_observables) < 1:
        return _usage(decoder, circuit_label, "DEM has no observables")
    if not any(inst.type == "error" for inst in dem.flattened()):
        return _usage(decoder, circuit_label, "DEM has no error mechanisms")
    distance = measure_distance(circuit)
    search_result = distance["stim_search_result"]
    if search_result is None and max_weight is None and sample_pairs is None:
        payload = _unavailable(
            decoder,
            f"UNAVAILABLE: {distance.get('search_failure')}",
            circuit_label,
        )
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            None,
            None,
            None,
            None,
        )
        return payload
    if search_result is None:
        correctable = None
        checked = 1 if max_weight is None else int(max_weight)
    else:
        correctable = (int(search_result) - 1) // 2
        checked = correctable if max_weight is None else int(max_weight)
    if checked < 0:
        checked = 0
    if checked > 2:
        checked = 2
    if max_weight is None and sample_pairs is None and checked < 1:
        shown = int(search_result)
        faults_for_scope = extract_faults(dem)
        message = (
            f"0 faults tested; Stim search result is {shown}, "
            f"so the derived cutoff is {int(checked)}; "
            "use --max-weight 1 to test single faults"
        )
        payload = _unavailable(decoder, message, circuit_label)
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            int(faults_for_scope["syndromes"].shape[0]),
            checked,
            correctable,
            None,
        )
        payload["checked_weight"] = int(checked)
        payload["singles_tested"] = 0
        payload["single_failures"] = 0
        payload["pairs_tested"] = None
        payload["pair_failures"] = None
        payload["enumeration_note"] = (
            "weight 2: not enumerated (0 faults tested; derived cutoff is 0)"
        )
        return payload
    deadline = None if timeout is None else _Deadline(float(timeout))
    try:
        decode_batch, unavailable = _call_within(deadline, load_decoder, decoder, dem)
    except _TimedOut:
        payload = _unavailable(decoder, _timeout_message(float(timeout)), circuit_label)
        payload["status"] = "TIMEOUT"
        payload["message"] = _timeout_message(float(timeout))
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            None,
            checked,
            correctable,
            None,
        )
        payload["checked_weight"] = checked
        payload["singles_tested"] = 0
        payload["single_failures"] = 0
        return payload
    except _FactoryUnavailable as exc:
        payload = _unavailable(decoder, f"UNAVAILABLE: {exc}", circuit_label)
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            None,
            checked,
            correctable,
            None,
        )
        return payload
    except _CorrelatedUnsupported as exc:
        payload = _unavailable(
            decoder,
            _correlated_unavailable(exc.version, exc.kind),
            circuit_label,
        )
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            None,
            checked,
            correctable,
            None,
        )
        return payload
    except Exception as exc:
        return _usage(
            decoder,
            circuit_label,
            f"{type(exc).__name__}: {_short(exc)}",
        )
    if unavailable:
        payload = _unavailable(decoder, unavailable, circuit_label)
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(dem.num_observables),
            None,
            checked,
            correctable,
            None,
        )
        return payload
    planted = getattr(decode_batch, "planted_fault_index", None)
    faults = extract_faults(dem)
    examples: list = []
    counts = _empty_attribution()
    reference, _reference_error = _load_reference(decoder, dem, decode_batch)
    single_failures = 0
    singles_tested = 0
    single_seconds = 0.0
    n_faults = int(faults["syndromes"].shape[0])
    if n_faults < 1:
        return _usage(decoder, circuit_label, "DEM has no error mechanisms")
    pair_space = n_faults * (n_faults - 1) // 2
    limit = DEFAULT_MAX_PAIRS if max_pairs is None else int(max_pairs)
    sampling = sample_pairs is not None
    try:
        if checked >= 1 and n_faults:
            started = time.perf_counter()
            predicted = _call_within(
                deadline,
                _call_decode,
                decode_batch,
                faults["syndromes"],
                int(faults["n_observables"]),
            )
            single_seconds = time.perf_counter() - started
            mask = _mismatch(predicted, faults["observables"])
            single_failures = _attribute_failures(
                reference,
                faults["syndromes"],
                faults["observables"],
                mask,
                counts,
                examples,
                lambda index, texts=faults["texts"]: {
                    "weight": 1,
                    "index": index,
                    "dem": texts[index],
                },
            )
            singles_tested = n_faults
        pair_info = {
            "pair_space": pair_space,
            "pairs_tested": 0,
            "pair_failures": 0,
            "exhaustive": True,
        }
        block_pairs = checked >= 2 and not sampling and pair_space > limit
        if block_pairs:
            per_row = (single_seconds / singles_tested) if singles_tested else 0.0
            estimated = per_row * pair_space
            suggest = _suggested_sample_size(pair_space, per_row)
            ratio = None
            scope = _stated_scope(
                decoder,
                noise,
                distance,
                int(faults["n_observables"]),
                n_faults,
                checked,
                correctable,
                ratio,
            )
            note = (
                "weight 2: not enumerated (0 pairs checked, reason "
                f"pair space {pair_space} is above the limit of {limit})"
            )
            if int(single_failures) > 0:
                if not examples or not examples[0].get("dem"):
                    raise RuntimeError("a counterexample was counted without DEM text")
                result = {
                    "command": "distance",
                    "status": "COUNTEREXAMPLE",
                    "exit_code": 1,
                    "circuit": circuit_label,
                    "decoder": decoder,
                    "message": examples[0]["dem"],
                    "stated_scope": scope,
                    "checked_weight": checked,
                    "singles_tested": singles_tested,
                    "single_failures": int(single_failures),
                    "pair_space": int(pair_space),
                    "pairs_tested": 0,
                    "pair_failures": None,
                    "failure_count": int(single_failures),
                    "counterexamples": examples,
                    "attribution": counts,
                    "reference_decoder": "pymatching",
                    "max_pairs": int(limit),
                    "estimated_seconds": round(estimated, 3),
                    "suggested_sample_pairs": int(suggest),
                    "pair_limit_hit": True,
                    "enumeration_note": note,
                }
                if counts["REFERENCE_ALSO_FAILS"]:
                    result["attribution_hint"] = REFERENCE_ALSO_FAILS_HINT
                if planted is not None:
                    result["toy_broken_fault_index"] = int(planted)
                return result
            message = (
                "UNAVAILABLE: weight-2 pair space is "
                f"{pair_space} pairs, above the limit of {limit}. "
                f"A timing measurement of {singles_tested} decoder rows took "
                f"{single_seconds:.6f}s; estimated exhaustive time is {estimated:.3f}s. "
                "Suggested command: python -m xcheck distance "
                f"--circuit {circuit_label} --decoder {decoder} "
                f"--sample-pairs {suggest}. "
                "Suggested command: python -m xcheck distance "
                f"--circuit {circuit_label} --decoder {decoder} "
                f"--max-pairs {pair_space}."
            )
            payload = _unavailable(decoder, message, circuit_label)
            payload["stated_scope"] = scope
            payload["checked_weight"] = checked
            payload["singles_tested"] = singles_tested
            payload["single_failures"] = int(single_failures)
            payload["pair_space"] = int(pair_space)
            payload["pairs_tested"] = 0
            payload["pair_failures"] = None
            payload["max_pairs"] = int(limit)
            payload["estimated_seconds"] = round(estimated, 3)
            payload["suggested_sample_pairs"] = int(suggest)
            payload["pair_limit_hit"] = True
            payload["enumeration_note"] = note
            return payload
        if checked >= 2 or sampling:
            pair_info = _check_pairs(
                decode_batch,
                faults,
                sample_pairs if sampling else None,
                examples,
                counts,
                reference,
                deadline,
            )
    except _TimedOut:
        scope = _stated_scope(
            decoder,
            noise,
            distance,
            int(faults["n_observables"]),
            n_faults,
            checked,
            correctable,
            None,
        )
        if examples:
            if not examples[0].get("dem"):
                raise RuntimeError("a counterexample was counted without DEM text")
            note = (
                f"enumeration stopped by timeout after {float(timeout):g}s; "
                "counterexamples found before the timeout are kept"
            )
            result = {
                "command": "distance",
                "status": "COUNTEREXAMPLE",
                "exit_code": 1,
                "circuit": circuit_label,
                "decoder": decoder,
                "message": examples[0]["dem"],
                "stated_scope": scope,
                "checked_weight": checked,
                "singles_tested": singles_tested,
                "single_failures": int(single_failures),
                "pair_space": int(pair_space),
                "pairs_tested": None,
                "pair_failures": None,
                "pair_failures_found_before_timeout": int(sum(counts.values())) - int(single_failures),
                "failure_count": int(sum(counts.values())),
                "counterexamples": examples,
                "attribution": counts,
                "reference_decoder": "pymatching",
                "enumeration_note": note,
            }
            if counts["REFERENCE_ALSO_FAILS"]:
                result["attribution_hint"] = REFERENCE_ALSO_FAILS_HINT
            if planted is not None:
                result["toy_broken_fault_index"] = int(planted)
            return result
        payload = _unavailable(decoder, _timeout_message(float(timeout)), circuit_label)
        payload["status"] = "TIMEOUT"
        payload["message"] = _timeout_message(float(timeout))
        payload["stated_scope"] = scope
        payload["checked_weight"] = checked
        payload["singles_tested"] = singles_tested
        payload["single_failures"] = int(single_failures)
        payload["pairs_tested"] = None
        payload["pair_failures"] = None
        payload["enumeration_note"] = (
            f"enumeration stopped by timeout after {float(timeout):g}s; "
            "weight 2: not enumerated"
        )
        return payload
    except _CorrelatedUnsupported as exc:
        payload = _unavailable(
            decoder,
            _correlated_unavailable(exc.version, exc.kind),
            circuit_label,
        )
        payload["stated_scope"] = _stated_scope(
            decoder,
            noise,
            distance,
            int(faults["n_observables"]),
            n_faults,
            checked,
            correctable,
            None,
        )
        return payload
    except DecoderOutputInvalid as exc:
        if examples:
            if not examples[0].get("dem"):
                raise RuntimeError("a counterexample was counted without DEM text")
            checked_pairs = int(pair_info["pairs_tested"])
            note = (
                "weight 2: not enumerated "
                f"({checked_pairs} pairs checked, reason {exc})"
            )
            scope = _stated_scope(
                decoder,
                noise,
                distance,
                int(faults["n_observables"]),
                n_faults,
                checked,
                correctable,
                None,
            )
            result = {
                "command": "distance",
                "status": "COUNTEREXAMPLE",
                "exit_code": 1,
                "circuit": circuit_label,
                "decoder": decoder,
                "message": examples[0]["dem"],
                "stated_scope": scope,
                "checked_weight": checked,
                "singles_tested": singles_tested,
                "single_failures": int(single_failures),
                "pair_space": int(pair_space),
                "pairs_tested": checked_pairs,
                "pair_failures": None,
                "failure_count": int(single_failures),
                "counterexamples": examples,
                "attribution": counts,
                "reference_decoder": "pymatching",
                "enumeration_note": note,
            }
            if counts["REFERENCE_ALSO_FAILS"]:
                result["attribution_hint"] = REFERENCE_ALSO_FAILS_HINT
            if planted is not None:
                result["toy_broken_fault_index"] = int(planted)
            return result
        return _decoder_output_invalid(decoder, circuit_label, exc)
    failure_count = int(single_failures + pair_info["pair_failures"])
    ratio = None
    if sampling:
        ratio = f"{int(pair_info['pairs_tested'])}/{int(pair_info['pair_space'])}"
    scope = _stated_scope(
        decoder,
        noise,
        distance,
        int(faults["n_observables"]),
        n_faults,
        checked,
        correctable,
        ratio,
    )
    if failure_count:
        if not examples or not examples[0].get("dem"):
            raise RuntimeError("a counterexample was counted without DEM text")
        status = "COUNTEREXAMPLE"
        exit_code = 1
        message = examples[0]["dem"]
    elif sampling:
        status = "SAMPLED_NONE"
        exit_code = 3
        message = f"{SCOPE_PHRASE}; {NOT_A_GUARANTEE}; sampling ratio {ratio}"
    elif checked >= 2 and not pair_info["exhaustive"]:
        payload = _unavailable(
            decoder,
            "UNAVAILABLE: the weight-2 enumeration did not finish",
            circuit_label,
        )
        payload["stated_scope"] = scope
        return payload
    else:
        status = "EXHAUSTIVE_NONE"
        exit_code = 0
        message = SCOPE_PHRASE
        if correctable is not None and correctable > checked:
            message += (
                f" Enumerated weights stop at {checked}; "
                f"the cutoff from the Stim search result was {correctable}."
            )
    result = {
        "command": "distance",
        "status": status,
        "exit_code": exit_code,
        "circuit": circuit_label,
        "decoder": decoder,
        "message": message,
        "stated_scope": scope,
        "checked_weight": checked,
        "singles_tested": singles_tested,
        "single_failures": int(single_failures),
        "pair_space": int(pair_info["pair_space"]),
        "pairs_tested": int(pair_info["pairs_tested"]) if (sampling or checked >= 2) else None,
        "pair_failures": int(pair_info["pair_failures"]) if (sampling or checked >= 2) else None,
        "failure_count": failure_count,
        "counterexamples": examples,
        "attribution": counts,
        "reference_decoder": "pymatching",
    }
    if counts["REFERENCE_ALSO_FAILS"]:
        result["attribution_hint"] = REFERENCE_ALSO_FAILS_HINT
    if planted is not None:
        result["toy_broken_fault_index"] = int(planted)
    if not sampling and checked < 2:
        result["enumeration_note"] = (
            "weight 2: not enumerated (pair faults were not checked)"
        )
    return result


def _unavailable(decoder: str, message: str, circuit: str | None) -> dict:
    text = message if str(message).startswith("UNAVAILABLE") else f"UNAVAILABLE: {message}"
    return {
        "command": "distance",
        "status": "UNAVAILABLE",
        "exit_code": 4,
        "circuit": circuit,
        "decoder": decoder,
        "failure_count": None,
        "counterexamples": [],
        "message": text,
    }


def _decoder_output_invalid(decoder: str, circuit: str | None, exc: DecoderOutputInvalid) -> dict:
    actual = exc.actual
    if isinstance(actual, tuple):
        actual_json = list(actual)
    else:
        actual_json = actual
    return {
        "command": "distance",
        "status": "DECODER_OUTPUT_INVALID",
        "exit_code": 2,
        "circuit": circuit,
        "decoder": decoder,
        "failure_count": None,
        "counterexamples": [],
        "message": str(exc),
        "expected_shape": list(exc.expected),
        "actual_shape": actual_json,
    }


def _usage(decoder: str, circuit: str | None, message: str) -> dict:
    return {
        "command": "distance",
        "status": "USAGE",
        "exit_code": 2,
        "circuit": circuit,
        "decoder": decoder,
        "failure_count": None,
        "counterexamples": [],
        "message": message,
    }


def format_text(result: dict) -> str:
    lines = [
        f"status: {result['status']}",
        f"decoder: {result.get('decoder')}",
        f"circuit: {result.get('circuit')}",
    ]
    scope = result.get("stated_scope") or {}
    versions = scope.get("versions") or {}
    if versions:
        rendered = " ".join(f"{key}={versions[key]}" for key in sorted(versions))
        lines.append(f"versions: {rendered}")
    noise = scope.get("noise_model") or {}
    if noise.get("statement"):
        lines.append(f"noise_model: {noise['statement']}")
        if noise.get("instruction_counts") is not None:
            lines.append(f"noise_instruction_counts: {json.dumps(noise['instruction_counts'], sort_keys=True)}")
    decomposition = scope.get("decomposition") or {}
    if decomposition.get("method"):
        lines.append(f"decomposition: {decomposition['method']}")
        lines.append(f"fault_unit: {decomposition['fault_unit']}")
    if scope.get("observable_count") is not None:
        lines.append(f"observable_count: {scope['observable_count']}")
    distance = scope.get("distance") or {}
    if distance.get("label"):
        lines.append(f"distance: {distance['label']}: {distance.get('stim_search_result')}")
        lines.append(f"search_params: {json.dumps(distance.get('search_params'), sort_keys=True)}")
        lines.append(f"graphlike_weight: {distance.get('graphlike_weight')}")
        lines.append(f"search_weight: {distance.get('search_weight')}")
    if scope.get("cutoff_statement"):
        lines.append(f"cutoff: {scope['cutoff_statement']}")
    if result.get("pair_limit_hit"):
        lines.append(f"checked_weight: {result.get('checked_weight')}")
        lines.append(
            f"single_failures: {result.get('single_failures')}/{result.get('singles_tested')}"
        )
        lines.append("pair_failures: not enumerated")
        lines.append(f"pair_space: {result.get('pair_space')}")
        lines.append(f"max_pairs: {result.get('max_pairs')}")
        lines.append(f"estimated_seconds: {result.get('estimated_seconds')}")
        if result.get("enumeration_note"):
            lines.append(str(result["enumeration_note"]))
    elif result.get("checked_weight") is not None:
        lines.append(f"checked_weight: {result.get('checked_weight')}")
        lines.append(
            f"single_failures: {result.get('single_failures')}/{result.get('singles_tested')}"
        )
        weight = int(result.get("checked_weight") or 0)
        pairs_omitted = weight < 2 or result.get("pair_failures") is None
        if result.get("pair_failures_found_before_timeout") is not None:
            lines.append(
                "pair_failures: partial ("
                f"{result.get('pair_failures_found_before_timeout')} failing pairs found before the timeout; "
                f"not all {result.get('pair_space')} pairs were checked)"
            )
        elif scope.get("sampling_ratio") is None and pairs_omitted:
            lines.append("pair_failures: not enumerated")
        else:
            lines.append(
                "pair_failures: "
                f"{result.get('pair_failures')}/{result.get('pairs_tested')}/{result.get('pair_space')}"
            )
        if result.get("failure_count") is not None:
            lines.append(f"failure_count: {result.get('failure_count')}")
        if result.get("enumeration_note"):
            lines.append(str(result["enumeration_note"]))
    attribution = result.get("attribution")
    if attribution:
        rendered = " ".join(f"{key}={attribution.get(key, 0)}" for key in _ATTRIBUTION_KEYS)
        lines.append(f"attribution: {rendered}")
    if result.get("attribution_hint"):
        lines.append(f"attribution_hint: {result['attribution_hint']}")
    if scope.get("sampling_ratio") is not None:
        lines.append(f"sampling ratio: {scope['sampling_ratio']}")
        lines.append(NOT_A_GUARANTEE)
    if result.get("message"):
        lines.append(f"message: {result['message']}")
    for item in result.get("counterexamples") or []:
        label = item.get("attribution")
        prefix = f"counterexample: {label}: " if label else "counterexample: "
        lines.append(prefix + str(item.get("dem")))
    lines.append(f"exit: {result['exit_code']}")
    return "\n".join(lines)


def check_path(
    path: str,
    decoder: str,
    max_weight: int | None = None,
    sample_pairs: int | None = None,
    max_pairs: int | None = None,
    timeout: float | None = None,
) -> dict:
    try:
        stim = _import_stim()
    except ImportError:
        return _unavailable(decoder, "UNAVAILABLE: stim is not installed", path)
    file_path = Path(path)
    if not file_path.is_file():
        return _usage(decoder, path, "circuit file not found")
    try:
        circuit = stim.Circuit.from_file(path)
    except Exception as exc:
        return _usage(decoder, path, f"{type(exc).__name__}: {_short(exc)}")
    return run_check(
        path,
        circuit,
        decoder,
        max_weight=max_weight,
        sample_pairs=sample_pairs,
        max_pairs=max_pairs,
        timeout=timeout,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m xcheck distance",
        add_help=True,
    )
    parser.add_argument("--circuit", required=True, help="Stim circuit file")
    parser.add_argument(
        "--decoder",
        default="pymatching",
        help=(
            "pymatching, pymatching-correlated, tesseract, toy-broken, "
            "or custom:module:function"
        ),
    )
    parser.add_argument("--max-weight", type=int, choices=(1, 2), default=None)
    parser.add_argument("--sample-pairs", type=int, default=None)
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help=f"weight-2 pair limit (default {DEFAULT_MAX_PAIRS})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="stop after this many seconds; a counterexample already found is kept",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        return int(exc.code)
    decoder = args.decoder
    known = decoder in _DECODERS or decoder.startswith("custom:")
    if not known or custom_spec_error(decoder):
        print(
            "usage: python -m xcheck distance --circuit <stim file> "
            "[--decoder pymatching|pymatching-correlated|tesseract|toy-broken|"
            "custom:module:function] "
            "[--max-weight 1|2] [--sample-pairs N] [--max-pairs N] [--timeout SEC] [--json]",
            file=sys.stderr,
        )
        return 2
    if args.sample_pairs is not None and args.sample_pairs < 1:
        print("sample-pairs must be a positive integer", file=sys.stderr)
        return 2
    if args.max_pairs is not None and args.max_pairs < 1:
        print("max-pairs must be a positive integer", file=sys.stderr)
        return 2
    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        print("timeout must be a positive number of seconds", file=sys.stderr)
        return 2
    result = check_path(
        args.circuit,
        decoder,
        max_weight=args.max_weight,
        sample_pairs=args.sample_pairs,
        max_pairs=args.max_pairs,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return int(result["exit_code"])
