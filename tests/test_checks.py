"""Healthy conversions must pass. The known suite must run. No network."""

from __future__ import annotations

import json
import re

import cirq
import stim
from qiskit import QuantumCircuit

from xcheck.__main__ import main
from xcheck.cirq_control import check_circuit as check_cirq
from xcheck.env import ensure_cache_env
from xcheck.known.suite import run_known
from xcheck.qasm3_rt import check_circuit as check_qasm
from xcheck.stim_cirq import check_circuit as check_stim

_CJK = re.compile(r"[\u4e00-\u9fff]")


def test_stim_cirq_roundtrip_healthy():
    circuit = stim.Circuit(
        "R 0\n"
        "M 0\n"
        "DETECTOR rec[-1]\n"
        "OBSERVABLE_INCLUDE(0) rec[-1]\n"
    )
    result = check_stim(circuit, "healthy-reset-measure")
    assert result["status"] == "pass", result
    assert result["broken"] == []


def test_cirq_classical_control_healthy():
    q0, q1 = cirq.LineQubit.range(2)
    circuit = cirq.Circuit(
        cirq.X(q0),
        cirq.measure(q0, key="m"),
        cirq.X(q1).with_classical_controls(cirq.KeyCondition(cirq.MeasurementKey("m"))),
        cirq.measure(q1, key="out"),
    )
    result = check_cirq(circuit, "healthy-latest-key", use_oracle=True)
    assert result["status"] == "pass", result
    assert result["broken"] == []
    assert result["invariants"]["oracle"]["bits"]["out"] == [[1]]


def test_qasm3_roundtrip_healthy():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    result = check_qasm(circuit, "healthy-bell-prep")
    assert result["status"] == "pass", result
    assert result["broken"] == []
    assert result["invariants"]["operator_equal"] is True


def test_known_suite_runs():
    payload = run_known()
    assert payload["check"] == "known"
    assert len(payload["cases"]) == 18
    ids = [row["id"] for row in payload["cases"]]
    assert ids[-3:] == ["stim-1146-grid", "stim-1146-float32", "pymatching-193-d3"]
    assert payload["watch_only"] == ["pymatching-193-d3"]
    assert payload["cases"][-1]["watch_only"] is True
    assert set(payload["counts"]) >= {"PASS", "FAIL", "UNAVAILABLE", "ERROR"}
    assert payload["exit_code"] in (0, 1, 2)
    header = payload["table"].splitlines()[0]
    assert header == "| id | status | issue | summary | expected | observed | mark |"
    blob = payload["table"] + json.dumps(payload["cases"])
    assert _CJK.search(blob) is None
    assert "/Users/" not in blob
    assert "UNAVAILABLE" in payload["counts"]


def test_cli_usage_is_english(capsys):
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "usage: python -m xcheck known" in err
    assert "--oracle" in err
    assert _CJK.search(err) is None


def test_cache_dirs_follow_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    ensure_cache_env()
    assert (tmp_path / "mplconfig").is_dir()
    assert (tmp_path / "xdg_cache").is_dir()
