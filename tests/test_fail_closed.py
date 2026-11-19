"""Fail closed: a bad decoder output or an unfinished check must not exit 0."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from xcheck.distance import main
from xcheck.known.suite import prediction_matches_observable

_D3 = Path(__file__).resolve().parents[1] / "examples" / "rotated_memory_z_d3_r3.stim"
_THREE = """
X_ERROR(0.1) 0
X_ERROR(0.1) 1
X_ERROR(0.1) 2
M 0 1 2
DETECTOR rec[-3]
DETECTOR rec[-2]
DETECTOR rec[-1]
OBSERVABLE_INCLUDE(0) rec[-1]
"""
_NO_OBS = """
X_ERROR(0.1) 0
M 0
DETECTOR rec[-1]
"""
_EMPTY_DEM = """
M 0
DETECTOR rec[-1]
OBSERVABLE_INCLUDE(0) rec[-1]
"""
_DECODERS = """
import numpy as np

def _rows(dets):
    return int(np.atleast_2d(np.asarray(dets)).shape[0])

def wide(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.zeros((_rows(dets), dem.num_observables + 1), dtype=np.uint8)
    return Decoder()

def narrow(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.zeros((_rows(dets), 0), dtype=np.uint8)
    return Decoder()

def short_rows(dem):
    class Decoder:
        def decode_batch(self, dets):
            rows = _rows(dets)
            return np.zeros((max(rows - 1, 0), dem.num_observables), dtype=np.uint8)
    return Decoder()

def value_two(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.full((_rows(dets), dem.num_observables), 2, dtype=np.int16)
    return Decoder()

def value_negative(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.full((_rows(dets), dem.num_observables), -1, dtype=np.int16)
    return Decoder()

def returns_none(dem):
    class Decoder:
        def decode_batch(self, dets):
            return None
    return Decoder()

def one_dimensional(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.zeros((_rows(dets),), dtype=np.uint8)
    return Decoder()

def raises(dem):
    class Decoder:
        def decode_batch(self, dets):
            raise RuntimeError("boom")
    return Decoder()

def zeros(dem):
    class Decoder:
        def decode_batch(self, dets):
            return np.zeros((_rows(dets), dem.num_observables), dtype=np.uint8)
    return Decoder()

def oracle(dem):
    syndromes = []
    observables = []
    n_det = int(dem.num_detectors)
    n_obs = int(dem.num_observables)
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        syn = np.zeros(n_det, dtype=np.uint8)
        obs = np.zeros(n_obs, dtype=np.uint8)
        for target in inst.targets_copy():
            if target.is_relative_detector_id():
                syn[target.val] ^= 1
            elif target.is_logical_observable_id():
                obs[target.val] ^= 1
        syndromes.append(syn)
        observables.append(obs)
    syn_m = np.stack(syndromes)
    obs_m = np.stack(observables)

    class Decoder:
        def decode_batch(self, dets):
            rows = np.atleast_2d(np.asarray(dets, dtype=np.uint8))
            out = np.zeros((rows.shape[0], n_obs), dtype=np.uint8)
            n = syn_m.shape[0]
            for row_i, row in enumerate(rows):
                found = False
                for i in range(n):
                    if np.array_equal(syn_m[i], row):
                        out[row_i] = obs_m[i]
                        found = True
                        break
                if found:
                    continue
                for i in range(n):
                    for j in range(i + 1, n):
                        if np.array_equal(np.bitwise_xor(syn_m[i], syn_m[j]), row):
                            out[row_i] = np.bitwise_xor(obs_m[i], obs_m[j])
                            found = True
                            break
                    if found:
                        break
            return out
    return Decoder()
"""


def _json(argv: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, json.loads(buffer.getvalue())


def _text(argv: list[str]) -> tuple[int, str]:
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


def test_known_prediction_does_not_drop_columns():
    assert prediction_matches_observable(np.array([0, 1]), np.array([0])) == "invalid"
    assert prediction_matches_observable(np.array([0]), np.array([0])) == "match"
    assert prediction_matches_observable(np.array([1]), np.array([0])) == "mismatch"
    assert prediction_matches_observable(np.array([2]), np.array([0])) == "invalid"


def test_decoder_contract_and_unfinished_checks_do_not_pass(tmp_path, monkeypatch):
    module = tmp_path / "fail_closed_decoders.py"
    module.write_text(_DECODERS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "three.stim").write_text(_THREE, encoding="utf-8")
    (tmp_path / "no_obs.stim").write_text(_NO_OBS, encoding="utf-8")
    (tmp_path / "empty_dem.stim").write_text(_EMPTY_DEM, encoding="utf-8")

    cases = []

    def add(name: str, code: int, status: str) -> None:
        assert code != 0, name
        cases.append((name, status, code))

    spec = "custom:fail_closed_decoders:{}"
    contract = [
        ("extra columns", "wide", "expected (286, 1) got (286, 2)"),
        ("fewer columns", "narrow", "expected (286, 1) got (286, 0)"),
        ("wrong row count", "short_rows", "expected (286, 1) got (285, 1)"),
        ("value 2", "value_two", "values must be 0 or 1"),
        ("value -1", "value_negative", "values must be 0 or 1"),
        ("returns None", "returns_none", "got None"),
        ("one-dimensional", "one_dimensional", "expected (286, 1) got (286,)"),
        ("raises", "raises", "got exception RuntimeError"),
    ]
    for name, function, snippet in contract:
        code, payload = _json(
            [
                "--circuit",
                str(_D3),
                "--decoder",
                spec.format(function),
                "--max-weight",
                "1",
                "--json",
            ]
        )
        assert payload["status"] == "DECODER_OUTPUT_INVALID"
        assert payload["exit_code"] == 2
        assert snippet in payload["message"]
        assert payload["counterexamples"] == []
        add(name, code, payload["status"])

    code = main(["--circuit", str(_D3), "--max-pairs", "0"])
    add("max-pairs 0", code, "USAGE")

    code, text = _text(
        [
            "--circuit",
            str(_D3),
            "--decoder",
            "pymatching-correlated",
            "--max-weight",
            "2",
            "--max-pairs",
            "1",
        ]
    )
    assert "status: COUNTEREXAMPLE" in text
    assert "single_failures: 6/286" in text
    assert text.count("counterexample:") == 6
    assert "weight 2: not enumerated (0 pairs checked, reason" in text
    assert "exit: 1" in text
    add("max-pairs 1 after a counterexample", code, "COUNTEREXAMPLE")

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            spec.format("oracle"),
            "--max-weight",
            "1",
            "--json",
        ]
    )
    pair_space = int(payload["pair_space"])
    assert pair_space >= 2
    assert code == 0

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            spec.format("oracle"),
            "--max-weight",
            "2",
            "--max-pairs",
            str(pair_space - 1),
            "--json",
        ]
    )
    assert payload["status"] == "UNAVAILABLE"
    add("max-pairs one below the pair count", code, payload["status"])

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            spec.format("zeros"),
            "--max-weight",
            "2",
            "--max-pairs",
            str(pair_space),
            "--json",
        ]
    )
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["counterexamples"]
    add("max-pairs equal to the pair count", code, payload["status"])

    code, payload = _json(["--circuit", "no_obs.stim", "--decoder", "pymatching", "--json"])
    assert payload["status"] == "USAGE"
    assert "no observables" in payload["message"]
    add("no observables", code, payload["status"])

    code, payload = _json(["--circuit", "empty_dem.stim", "--decoder", "pymatching", "--json"])
    assert payload["status"] == "USAGE"
    assert "no error mechanisms" in payload["message"]
    add("empty DEM", code, payload["status"])

    code = main(["--circuit", str(_D3), "--max-weight", "3"])
    add("max-weight out of range", code, "USAGE")

    code, payload = _json(["--circuit", str(_D3), "--decoder", "toy-broken", "--json"])
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["counterexamples"]
    add("toy-broken", code, payload["status"])

    rendered = "\n".join(f"{name}\t{status}\t{exit_code}" for name, status, exit_code in cases)
    assert "\t0" not in rendered
    assert len(cases) == 16
