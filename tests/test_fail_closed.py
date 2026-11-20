"""Fail closed: a bad decoder output or an unfinished check must not exit 0."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from xcheck.distance import SCOPE_PHRASE, main
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


_ZERO_FAULTS = (
    "0 faults tested; Stim search result is 2, so the derived cutoff is 0; "
    "use --max-weight 1 to test single faults"
)


def test_help_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    from xcheck.__main__ import main as program_main

    assert program_main(["--help"]) == 0
    assert program_main(["-h"]) == 0
    assert program_main(["distance", "--help"]) == 0
    assert program_main([]) == 2


def test_default_weight_one_json_pair_fields_are_null():
    code, payload = _json(
        ["--circuit", str(_D3), "--decoder", "pymatching", "--json"]
    )
    assert code == 0
    assert payload["status"] == "EXHAUSTIVE_NONE"
    assert payload["singles_tested"] == 286
    assert payload["pairs_tested"] is None
    assert payload["pair_failures"] is None
    assert "not enumerated" in payload["enumeration_note"]
    text_code, text = _text(["--circuit", str(_D3), "--decoder", "pymatching"])
    assert text_code == 0
    assert "pair_failures: not enumerated" in text


def test_cutoff_zero_is_unavailable_until_max_weight_one(tmp_path, monkeypatch):
    import stim

    monkeypatch.chdir(tmp_path)
    stim.Circuit.generated(
        "color_code:memory_xyz",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
    ).to_file("color.stim")
    code, payload = _json(["--circuit", "color.stim", "--decoder", "pymatching", "--json"])
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert payload["singles_tested"] == 0
    assert _ZERO_FAULTS in payload["message"]
    assert SCOPE_PHRASE not in payload["message"]
    assert "no counterexample" not in payload["message"]

    code, payload = _json(
        [
            "--circuit",
            "color.stim",
            "--decoder",
            "pymatching",
            "--max-weight",
            "1",
            "--json",
        ]
    )
    assert payload["checked_weight"] == 1
    assert payload["singles_tested"] > 0
    assert payload["pairs_tested"] is None
    assert payload["pair_failures"] is None
    assert "0 faults tested" not in payload["message"]
    if payload["single_failures"]:
        assert code == 1
        assert payload["status"] == "COUNTEREXAMPLE"
        assert payload["counterexamples"]
    else:
        assert code == 0
        assert payload["status"] == "EXHAUSTIVE_NONE"
        assert payload["message"].startswith(SCOPE_PHRASE)


def test_factory_exception_is_unavailable_and_bad_args_stay_usage(tmp_path, monkeypatch):
    module = tmp_path / "factory_boom.py"
    module.write_text(
        "def factory(dem):\n"
        "    raise ValueError('Expected all detectors to have at least 4 coordinates')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "three.stim").write_text(_THREE, encoding="utf-8")
    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            "custom:factory_boom:factory",
            "--max-weight",
            "1",
            "--json",
        ]
    )
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert "ValueError" in payload["message"]
    assert "Expected all detectors to have at least 4 coordinates" in payload["message"]
    assert main(["--circuit", "three.stim", "--max-weight", "3"]) == 2
    assert main(["--circuit", "three.stim", "--timeout", "0"]) == 2
    assert main(["--circuit", "three.stim", "--decoder", "custom:not_a_spec"]) == 2

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            "custom:missing_mod_zz:factory",
            "--max-weight",
            "1",
            "--json",
        ]
    )
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert "missing_mod_zz" in payload["message"]
    assert "ModuleNotFoundError" in payload["message"]


def test_timeout_stops_without_claiming_no_counterexample(tmp_path, monkeypatch):
    module = tmp_path / "sleepy.py"
    module.write_text(
        "import time\n"
        "import numpy as np\n"
        "\n"
        "class Slow:\n"
        "    def __init__(self, dem):\n"
        "        self.n_obs = dem.num_observables\n"
        "        self.calls = 0\n"
        "\n"
        "    def decode_batch(self, dets):\n"
        "        self.calls += 1\n"
        "        rows = np.atleast_2d(np.asarray(dets))\n"
        "        if self.calls == 1:\n"
        "            return np.ones((rows.shape[0], self.n_obs), dtype=np.uint8)\n"
        "        time.sleep(1.5)\n"
        "        return np.zeros((rows.shape[0], self.n_obs), dtype=np.uint8)\n"
        "\n"
        "def hit_then_sleep(dem):\n"
        "    return Slow(dem)\n"
        "\n"
        "def always_sleep(dem):\n"
        "    class Decoder:\n"
        "        def decode_batch(self, dets):\n"
        "            time.sleep(1.5)\n"
        "            rows = np.atleast_2d(np.asarray(dets))\n"
        "            return np.zeros((rows.shape[0], dem.num_observables), dtype=np.uint8)\n"
        "    return Decoder()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "three.stim").write_text(_THREE, encoding="utf-8")

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            "custom:sleepy:always_sleep",
            "--max-weight",
            "1",
            "--timeout",
            "0.3",
            "--json",
        ]
    )
    assert code == 4
    assert payload["status"] == "TIMEOUT"
    assert payload["exit_code"] == 4
    assert payload["counterexamples"] == []
    assert SCOPE_PHRASE not in payload["message"]
    assert "no counterexample" not in payload["message"]
    assert "TIMEOUT" in payload["message"]

    code, payload = _json(
        [
            "--circuit",
            "three.stim",
            "--decoder",
            "custom:sleepy:hit_then_sleep",
            "--max-weight",
            "2",
            "--timeout",
            "0.3",
            "--json",
        ]
    )
    assert code == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["exit_code"] == 1
    assert payload["counterexamples"]
    assert "error(" in payload["counterexamples"][0]["dem"]
    assert SCOPE_PHRASE not in payload["message"]
    assert "no counterexample" not in payload["message"]


def test_timeout_during_pairs_reports_partial_pair_failures():
    """Claude 2026-11-20: a timeout during pair enumeration keeps COUNTEREXAMPLE and reports the partial pair count."""
    import subprocess, sys, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=root)
    p = subprocess.run([sys.executable, "-m", "xcheck", "distance", "--circuit",
                        os.path.join(root, "examples", "rotated_memory_z_d5_r5.stim"),
                        "--decoder", "pymatching-correlated", "--max-weight", "2", "--timeout", "1"],
                       capture_output=True, text=True, env=env)
    if "pair_failures: 1173/" in p.stdout:
        return  # machine fast enough to finish inside the timeout; nothing partial to check
    assert p.returncode == 1, p.stdout
    assert "status: COUNTEREXAMPLE" in p.stdout
    assert "pair_failures: partial (" in p.stdout
    assert "pair_failures: not enumerated" not in p.stdout
