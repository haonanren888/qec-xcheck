"""Distance command: toy-broken control, historical PyMatching counts, scope text."""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from xcheck.distance import (
    DEFAULT_MAX_PAIRS,
    DISTANCE_LABEL,
    FAULT_UNIT,
    NOT_A_GUARANTEE,
    REFERENCE_ALSO_FAILS_HINT,
    SCOPE_PHRASE,
    format_text,
    main,
    ranks_to_pairs,
    run_check,
)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_BANNED = ("verified", "reliable", "certified", "passes all", "exact code distance", "exact distance")
_D3 = "examples/rotated_memory_z_d3_r3.stim"
_D5 = "examples/rotated_memory_z_d5_r5.stim"
_TINY = """
X_ERROR(0.1) 0
X_ERROR(0.1) 1
M 0 1
DETECTOR rec[-2]
DETECTOR rec[-1]
OBSERVABLE_INCLUDE(0) rec[-2]
OBSERVABLE_INCLUDE(1) rec[-1]
"""
_ORACLE = """
import numpy as np

def factory(dem):
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
    syn_m = np.stack(syndromes) if syndromes else np.zeros((0, n_det), dtype=np.uint8)
    obs_m = np.stack(observables) if observables else np.zeros((0, n_obs), dtype=np.uint8)

    class Oracle:
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

    return Oracle()
"""


def test_ranks_round_trip_small_n():
    for n in (2, 5, 17, 64):
        total = n * (n - 1) // 2
        left, right = ranks_to_pairs(np.arange(total, dtype=np.int64), n)
        expect = [(i, j) for i in range(n) for j in range(i + 1, n)]
        assert list(zip(left.tolist(), right.tolist())) == expect


def test_toy_broken_is_counterexample():
    code, payload = _run(["--circuit", _D3, "--decoder", "toy-broken", "--json"])
    assert code == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["exit_code"] == 1
    assert payload["failure_count"] >= 1
    assert payload["counterexamples"]
    assert "error(" in payload["counterexamples"][0]["dem"]
    planted = payload["toy_broken_fault_index"]
    assert any(item.get("index") == planted for item in payload["counterexamples"])
    scope = payload["stated_scope"]
    assert scope["distance"]["label"] == DISTANCE_LABEL
    assert scope["distance"]["stim_search_result"] == 3
    assert scope["distance"]["search_params"]
    assert scope["decomposition"]["method"] == "detector_error_model(decompose_errors=True)"
    assert scope["decomposition"]["fault_unit"] == FAULT_UNIT
    assert "graph edge" in scope["decomposition"]["fault_unit"]
    assert scope["observable_count"] >= 1
    assert scope["noise_model"]["source"] == "circuit"
    assert scope["noise_model"]["instruction_counts"]
    _assert_public_text(payload)


def test_scope_statuses_on_tiny_circuit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tiny.stim").write_text(_TINY, encoding="utf-8")
    (tmp_path / "scope_oracle.py").write_text(_ORACLE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    code, payload = _run(
        [
            "--circuit",
            "tiny.stim",
            "--decoder",
            "custom:scope_oracle:factory",
            "--max-weight",
            "2",
            "--json",
        ]
    )
    assert code == 0
    assert payload["status"] == "EXHAUSTIVE_NONE"
    assert payload["message"] == SCOPE_PHRASE or payload["message"].startswith(SCOPE_PHRASE)
    assert payload["stated_scope"]["sampling_ratio"] is None
    assert payload["failure_count"] == 0
    assert payload["circuit"] == "tiny.stim"
    _assert_public_text(payload)

    code, payload = _run(
        [
            "--circuit",
            "tiny.stim",
            "--decoder",
            "custom:scope_oracle:factory",
            "--max-weight",
            "2",
            "--sample-pairs",
            "1",
            "--json",
        ]
    )
    assert code == 3
    assert payload["status"] == "SAMPLED_NONE"
    assert NOT_A_GUARANTEE in payload["message"]
    assert "sampling ratio" in payload["message"]
    assert payload["stated_scope"]["sampling_ratio"] == (
        f"{payload['pairs_tested']}/{payload['pair_space']}"
    )
    assert payload["counterexamples"] == []
    _assert_public_text(payload)

    text_code, text = _run_text(
        [
            "--circuit",
            "tiny.stim",
            "--decoder",
            "custom:scope_oracle:factory",
            "--sample-pairs",
            "1",
        ]
    )
    assert text_code == 3
    assert "status: SAMPLED_NONE" in text
    assert NOT_A_GUARANTEE in text
    assert "sampling ratio:" in text
    assert DISTANCE_LABEL in text
    assert FAULT_UNIT in text
    _assert_public_blob(text)


def test_sample_pairs_counterexample_is_not_sampled_none(tmp_path, monkeypatch):
    module = tmp_path / "sample_decoder.py"
    module.write_text(
        "import numpy as np\n"
        "\n"
        "class ZeroObs:\n"
        "    def __init__(self, dem):\n"
        "        self.n_obs = dem.num_observables\n"
        "\n"
        "    def decode_batch(self, dets):\n"
        "        rows = np.atleast_2d(np.asarray(dets))\n"
        "        return np.ones((rows.shape[0], self.n_obs), dtype=np.uint8)\n"
        "\n"
        "def factory(dem):\n"
        "    return ZeroObs(dem)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    code, payload = _run(
        [
            "--circuit",
            _D3,
            "--decoder",
            "custom:sample_decoder:factory",
            "--sample-pairs",
            "2",
            "--json",
        ]
    )
    assert code == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["failure_count"] > 0
    assert "error(" in payload["counterexamples"][0]["dem"]
    _assert_public_text(payload)


def test_pymatching_240_historical_counts():
    _skip_unless_pymatching_240()
    code, payload = _run(
        ["--circuit", _D3, "--decoder", "pymatching-correlated", "--json"]
    )
    assert code == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["single_failures"] == 6
    assert payload["singles_tested"] == 286
    assert payload["failure_count"] == 6
    assert len(payload["counterexamples"]) == 6
    assert payload["attribution"] == {
        "DECODER_SPECIFIC": 6,
        "REFERENCE_ALSO_FAILS": 0,
        "REFERENCE_UNAVAILABLE": 0,
    }
    assert all(item["attribution"] == "DECODER_SPECIFIC" for item in payload["counterexamples"])
    assert "attribution_hint" not in payload
    _assert_public_text(payload)
    text_code, text = _run_text(
        ["--circuit", _D3, "--decoder", "pymatching-correlated"]
    )
    assert text_code == 1
    assert "attribution: DECODER_SPECIFIC=6 REFERENCE_ALSO_FAILS=0 REFERENCE_UNAVAILABLE=0" in text
    assert "counterexample: DECODER_SPECIFIC:" in text

    code, payload = _run(["--circuit", _D3, "--decoder", "pymatching", "--json"])
    assert code == 0
    assert payload["status"] == "EXHAUSTIVE_NONE"
    assert payload["single_failures"] == 0
    assert payload["singles_tested"] == 286
    assert payload["message"].startswith(SCOPE_PHRASE)
    assert payload["attribution"] == {
        "DECODER_SPECIFIC": 0,
        "REFERENCE_ALSO_FAILS": 0,
        "REFERENCE_UNAVAILABLE": 0,
    }
    assert "attribution_hint" not in payload
    _assert_public_text(payload)

    import stim

    circuit = stim.Circuit.from_file(_D5)
    correlated = run_check(_D5, circuit, "pymatching-correlated")
    assert correlated["status"] == "COUNTEREXAMPLE"
    assert correlated["exit_code"] == 1
    assert correlated["single_failures"] == 0
    assert correlated["singles_tested"] == 1953
    assert correlated["pair_failures"] == 1173
    assert correlated["pairs_tested"] == 1906128
    assert "error(" in correlated["counterexamples"][0]["dem"]
    assert correlated["attribution"]["DECODER_SPECIFIC"] == 1173
    assert correlated["attribution"]["REFERENCE_ALSO_FAILS"] == 0
    assert correlated["attribution"]["REFERENCE_UNAVAILABLE"] == 0
    _assert_public_text(correlated)

    plain = run_check(
        "repetition-d3",
        stim.Circuit.generated(
            "repetition_code:memory",
            distance=3,
            rounds=3,
            after_clifford_depolarization=0.001,
        ),
        "pymatching",
        max_weight=2,
    )
    correlated_rep = run_check(
        "repetition-d3",
        stim.Circuit.generated(
            "repetition_code:memory",
            distance=3,
            rounds=3,
            after_clifford_depolarization=0.001,
        ),
        "pymatching-correlated",
        max_weight=2,
    )
    assert plain["status"] == "COUNTEREXAMPLE"
    assert plain["pair_failures"] == 70
    assert plain["pairs_tested"] == 351
    assert plain["single_failures"] == 0
    assert correlated_rep["pair_failures"] == 69
    assert correlated_rep["pairs_tested"] == 351
    assert correlated_rep["single_failures"] == 0


def test_repetition_d3_overwide_cutoff_reference_also_fails():
    _skip_unless_pymatching_240()
    import stim

    circuit = stim.Circuit.generated(
        "repetition_code:memory",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
    )
    payload = run_check("repetition-d3", circuit, "pymatching", max_weight=2)
    assert payload["exit_code"] == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["stated_scope"]["distance"]["stim_search_result"] == 3
    assert payload["checked_weight"] == 2
    assert payload["stated_scope"]["correctable_weight_from_search"] == 1
    assert payload["checked_weight"] > payload["stated_scope"]["correctable_weight_from_search"]
    assert payload["attribution"]["REFERENCE_ALSO_FAILS"] > 0
    assert payload["attribution"]["REFERENCE_ALSO_FAILS"] == payload["failure_count"]
    assert payload["attribution"]["DECODER_SPECIFIC"] == 0
    assert payload["attribution"]["REFERENCE_UNAVAILABLE"] == 0
    assert payload["attribution_hint"] == REFERENCE_ALSO_FAILS_HINT
    text = format_text(payload)
    assert "REFERENCE_ALSO_FAILS=" in text
    assert REFERENCE_ALSO_FAILS_HINT in text
    _assert_public_text(payload)
    _assert_public_blob(text)


def test_reference_unavailable_keeps_counterexample_exit(tmp_path, monkeypatch):
    module = tmp_path / "zero_decoder.py"
    module.write_text(
        "import numpy as np\n"
        "\n"
        "class ZeroObs:\n"
        "    def __init__(self, dem):\n"
        "        self.n_obs = dem.num_observables\n"
        "\n"
        "    def decode_batch(self, dets):\n"
        "        rows = np.atleast_2d(np.asarray(dets))\n"
        "        return np.ones((rows.shape[0], self.n_obs), dtype=np.uint8)\n"
        "\n"
        "def factory(dem):\n"
        "    return ZeroObs(dem)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    def _missing():
        raise ImportError("pymatching blocked for this test")

    monkeypatch.setattr("xcheck.distance._import_pymatching", _missing)
    code, payload = _run(
        [
            "--circuit",
            _D3,
            "--decoder",
            "custom:zero_decoder:factory",
            "--max-weight",
            "1",
            "--json",
        ]
    )
    assert code == 1
    assert payload["status"] == "COUNTEREXAMPLE"
    assert payload["exit_code"] == 1
    assert payload["failure_count"] > 0
    assert payload["attribution"]["REFERENCE_UNAVAILABLE"] == payload["failure_count"]
    assert payload["attribution"]["DECODER_SPECIFIC"] == 0
    assert payload["attribution"]["REFERENCE_ALSO_FAILS"] == 0
    assert "attribution_hint" not in payload
    assert all(
        item["attribution"] == "REFERENCE_UNAVAILABLE" for item in payload["counterexamples"]
    )


def test_skip_message_on_other_pymatching_version(monkeypatch, capsys):
    import pymatching

    monkeypatch.setattr(pymatching, "__version__", "9.9.9", raising=False)
    with pytest.raises(pytest.skip.Exception) as caught:
        _skip_unless_pymatching_240()
    assert "behavior may have changed; re-run and explain" in str(caught.value)
    captured = capsys.readouterr()
    assert "behavior may have changed; re-run and explain" in captured.out


def test_missing_tesseract_is_unavailable(monkeypatch):
    def _missing():
        raise ImportError("tesseract_decoder blocked for this test")

    monkeypatch.setattr("xcheck.distance._import_tesseract", _missing)
    code, payload = _run(["--circuit", _D3, "--decoder", "tesseract", "--json"])
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert payload["message"].startswith("UNAVAILABLE:")
    _assert_public_text(payload)


def test_missing_pymatching_is_unavailable(monkeypatch):
    def _missing():
        raise ImportError("pymatching blocked for this test")

    monkeypatch.setattr("xcheck.distance._import_pymatching", _missing)
    code, payload = _run(["--circuit", _D3, "--decoder", "pymatching", "--json"])
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert "pymatching" in payload["message"]
    _assert_public_text(payload)


def test_usage_errors():
    assert main([]) == 2
    assert main(["--decoder", "pymatching"]) == 2
    assert main(["--circuit", _D3, "--decoder", "other"]) == 2
    assert main(["--circuit", _D3, "--max-weight", "3"]) == 2
    assert main(["--circuit", _D3, "--sample-pairs", "0"]) == 2
    assert main(["--circuit", _D3, "--max-pairs", "0"]) == 2
    assert main(["--circuit", _D3, "--decoder", "custom:not_a_spec"]) == 2


def test_default_pair_limit_is_two_million():
    assert DEFAULT_MAX_PAIRS == 2_000_000
    assert 1_906_128 <= DEFAULT_MAX_PAIRS


def test_pair_limit_does_not_enumerate(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("pair enumeration started")

    monkeypatch.setattr("xcheck.distance._check_pairs", _boom)
    argv = [
        "--circuit",
        _D3,
        "--decoder",
        "pymatching",
        "--max-weight",
        "2",
        "--max-pairs",
        "10",
    ]
    code, payload = _run(argv + ["--json"])
    space = 286 * 285 // 2
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert payload["pair_space"] == space
    assert payload["pairs_tested"] == 0
    assert payload["max_pairs"] == 10
    assert payload["pair_limit_hit"] is True
    assert str(space) in payload["message"]
    assert "--sample-pairs" in payload["message"]
    assert "--max-pairs" in payload["message"]
    assert "estimated exhaustive time" in payload["message"]
    assert payload["estimated_seconds"] >= 0
    assert payload["suggested_sample_pairs"] >= 1
    text_code, text = _run_text(argv)
    assert text_code == 4
    assert "status: UNAVAILABLE" in text
    assert "pair_failures: not enumerated" in text
    assert f"pair_space: {space}" in text
    assert "estimated_seconds:" in text
    assert "Traceback" not in text
    _assert_public_blob(text)


def test_sample_pairs_ignores_pair_limit():
    code, payload = _run(
        [
            "--circuit",
            _D3,
            "--decoder",
            "pymatching",
            "--max-pairs",
            "1",
            "--sample-pairs",
            "1",
            "--json",
        ]
    )
    assert code in (1, 3)
    assert payload["status"] in ("COUNTEREXAMPLE", "SAMPLED_NONE")
    assert payload.get("pair_limit_hit") is not True


def test_correlated_constructor_typeerror_is_unavailable(monkeypatch):
    import pymatching

    original = pymatching.Matching.from_detector_error_model

    def wrapped(*args, **kwargs):
        if "enable_correlations" in kwargs:
            raise TypeError("unexpected keyword argument")
        return original(*args, **kwargs)

    monkeypatch.setattr(pymatching.Matching, "from_detector_error_model", wrapped)
    code, payload = _run(
        ["--circuit", _D3, "--decoder", "pymatching-correlated", "--json"]
    )
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert payload["exit_code"] == 4
    assert pymatching.__version__ in payload["message"]
    assert "enable_correlations" in payload["message"]
    assert "TypeError" in payload["message"]
    assert "Traceback" not in payload["message"]
    assert "unexpected keyword" not in payload["message"]


def test_correlated_decode_attributeerror_is_unavailable(monkeypatch):
    import pymatching

    original = pymatching.Matching.from_detector_error_model

    def wrapped(*args, **kwargs):
        kwargs.pop("enable_correlations", None)
        matcher = original(*args, **kwargs)
        real = matcher.decode_batch

        def decode_batch(*dargs, **dkwargs):
            if dkwargs.get("enable_correlations"):
                raise AttributeError("enable_correlations")
            return real(*dargs)

        matcher.decode_batch = decode_batch
        return matcher

    monkeypatch.setattr(pymatching.Matching, "from_detector_error_model", wrapped)
    code, payload = _run(
        ["--circuit", _D3, "--decoder", "pymatching-correlated", "--json"]
    )
    assert code == 4
    assert payload["status"] == "UNAVAILABLE"
    assert pymatching.__version__ in payload["message"]
    assert "enable_correlations" in payload["message"]
    assert "AttributeError" in payload["message"]
    assert "Traceback" not in payload["message"]


def _skip_unless_pymatching_240():
    import pymatching

    if pymatching.__version__ != "2.4.0":
        print("behavior may have changed; re-run and explain", flush=True)
        pytest.skip("behavior may have changed; re-run and explain")


def _run(argv: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    _assert_public_text(payload)
    return code, payload


def _run_text(argv: list[str]) -> tuple[int, str]:
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


def _assert_public_text(payload: dict) -> None:
    _assert_public_blob(json.dumps(payload))


def _assert_public_blob(blob: str) -> None:
    assert _CJK.search(blob) is None
    assert "/Users/" not in blob
    assert "@" not in blob
    lower = blob.lower()
    for banned in _BANNED:
        assert banned not in lower
