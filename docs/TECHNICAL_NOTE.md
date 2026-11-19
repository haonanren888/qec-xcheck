This note describes the known-defect suite as of 0.3.0; the 0.4.0 distance check is described in low-weight-vs-ler.md.

# qec-xcheck: silent changes in QEC circuit conversions

This note is for an engineer who uses Stim, Cirq, stimcirq, Sinter, or OpenQASM. It describes what `qec-xcheck` 0.3.0 checks, which published defects the prepared tree still reproduces, and what a failing row does not prove. The import name is `xcheck`. Facts are from that tree (`README.md`, `xcheck/known/suite.py`, `xcheck/known/circuits.py`, `xcheck/classical_ref.py`, `xcheck/cirq_control.py`, `xcheck/stim_cirq.py`, `xcheck/qasm3_rt.py`, `.github/workflows/xcheck.yml`). This note does not quote maintainer comments and does not say that an issue was confirmed, closed, or fixed. GitHub open or closed state for the cited issues is `open (checked 2026-11-19)` in the README.

## Problem

A QEC toolchain moves one circuit across representations. Stim carries detectors, observables, and `REPEAT` blocks. Cirq carries measurement keys, `CircuitOperation` fields (`repetitions`, `measurement_key_map`, classical controls), and JSON. OpenQASM 2 and 3 carry registers, slices, and classical conditions. Sinter collects shots, resumes from a file, and plots observable-error rates.

Those conversions can finish without an exception and still change a measurement record, a detector, an observable, or a classical condition. `qec-xcheck` is a regression suite for that class of change. `FAIL` means this install still disagrees with the cited specification. It is not a crash of the checker. `PASS` means this install matches that specification. `UNAVAILABLE` means the saved reproduction needs a component this interpreter does not have. `ERROR` means the check itself failed. A `watch_only` row records a problem reported by someone else and does not draft a comment. That mark does not change PASS or FAIL.

## Eighteen public cases

Each row is one deterministic fixture in `xcheck/known/`. The link is the public report that check cites. The result column is a local run, not a GitHub state and not a maintainer statement. The 2026-11-18 run of the fifteen 0.2.0 rows used Python 3.12.13, Cirq `1.8.0.dev20261117194631`, Stim/stimcirq/Sinter `1.17.dev1793242987`, Qiskit `2.6.2`, and `qiskit-qasm3-import` `0.6.0`. stimflow was not installed. That run exited 1 with 14 `FAIL`, 1 `UNAVAILABLE` (Stim #1132), and 0 `ERROR`. On 2026-11-19 the same version line, now with PyMatching `2.4.0` and NumPy `2.2.6`, ran all 18 rows and exited 1 with 17 `FAIL`, 1 `UNAVAILABLE` (Stim #1132), and 0 `ERROR`. One interpreter is not every release channel.

**Key or index remap.** Cirq documents `get_int` so index 0 is the earliest measurement and -1 is the latest. `cirq-8525`, `cirq-8525-bitmask`, `cirq-8525-json-index`, and `stim-1143` should give `out == [[0]]` (for the bitmask, measurements `(1, 0)` are integer 2 and `(2 & 1) == 1` is false). The self-test recorded `[[1]]`. `stim-1136` is the published rename, not a `qubit_map` taken from the title: `measurement_key_map` sends inner `b` to `a`, outer `b` stays 0, and the last sample bit should be 0. The self-test recorded `1`.

**Comparison rewritten.** [Cirq #8528](https://github.com/quantumlib/Cirq/issues/8528): measurement 0 substituted for a symbol is falsy, even with `positive=True`, so `out` should be `[[0]]`. The self-test recorded `[[1]]`. [Cirq #8529](https://github.com/quantumlib/Cirq/issues/8529): after swapping `a` and `b`, `b=1 > a=0` must still fire (`out == [[1]]`). The self-test recorded `[[0]]`.

**Multi-bit condition or slice.** [Cirq #8530](https://github.com/quantumlib/Cirq/issues/8530): big-endian `get_int` makes measured `[1, 0]` the integer 2, and an OpenQASM 2 export of `m == 2` must keep that branch. The self-test summary is `control bit 0 after export`. [qiskit-qasm3-import #69](https://github.com/Qiskit/qiskit-qasm3-import/issues/69): the check cites inclusive `q[3:-1:0]` as qubits `{3, 2, 1, 0}`. The self-test recorded `[]`.

**REPEAT.** [Stim #1145](https://github.com/quantumlib/Stim/issues/1145): outer `repetitions=1` must keep the inner repeat of 2, so two measurements and sample `[1, 0]`. The self-test recorded `num_measurements=0` and `sample=[]`. [Stim #1132](https://github.com/quantumlib/Stim/issues/1132): both two flat `error(0.125) L0` lines and the same line inside `repeat 2` are distance 1, so `stimflow.verify_distance_is_at_least(dem, 2)` must reject both. The row was `UNAVAILABLE` because stimflow was absent. The suite does not invent a circuit from the title, so this check was not shown to pass.

**Measurement width.** [Stim #1135](https://github.com/quantumlib/Stim/issues/1135): `MPP Z0*Z1 Z2` should yield one bit per Pauli product, cited as `{'0': [[[1]]], '1': [[[0]]]}`. The check says the stimcirq branch writes `len(targets)` as the width. The self-test recorded `IndexError`.

**Control value or confusion dropped.** [Stim #1142](https://github.com/quantumlib/Stim/issues/1142): `control_values=(0,)` enables `Z` when the control is 0; plus state, that gate, then `H` should measure 1. The self-test recorded `[[0]]`. [Stim #1144](https://github.com/quantumlib/Stim/issues/1144): a `confusion_map` that turns measured 1 into 0 must be kept, or the conversion must raise `NotImplementedError` or `ValueError`. The self-test recorded `[[1]]`.

**Resumed counts.** [Stim #1137](https://github.com/quantumlib/Stim/issues/1137): collect 16 shots, resume to 32 with observable-error counts, and `obs_mistake_mask=E_` must be `hits=32`, `best=1`. The check cites bits `10` against prediction `00`, and `_split_custom_counts` moving custom counts into `errors` while `shots` stays 32. The 2026-11-18 self-test recorded `hits=16` and `best=0.5`.

**Binomial fit.** [Stim #1146](https://github.com/quantumlib/Stim/issues/1146): `stim-1146-grid` uses n=10^6, one hit, and likelihood factor 1000. The exact lower edge is a log-space likelihood-ratio bisection, about `1/(e*F*n)`. A ratio of sinter's lower edge over that exact edge above 2 is `FAIL`; a ratio of at most 1.05 is `PASS`. `stim-1146-float32` uses n=10^9, hits=10^8, and the same factor. A float32 log-likelihood must not stretch the upper half-width past 1.05 times the exact half-width. The published report describes that half-width as about 1.50 times exact.

**Correlated matching, watch only.** [PyMatching #193](https://github.com/oscarhiggott/PyMatching/issues/193): `surface_code:rotated_memory_z`, distance 3, 3 rounds, `after_clifford_depolarization=0.001`, `detector_error_model(decompose_errors=True)`, `enable_correlations=True`. Every single fault should decode to that fault's observable. The row is `watch_only`: the suite records the result and does not draft a comment. A failure count above 0 is `FAIL`.

| id | mechanism | issue | self-test, 2026-11-18 |
| --- | --- | --- | --- |
| cirq-8525 | key/index remap | [Cirq #8525](https://github.com/quantumlib/Cirq/issues/8525) | FAIL `[[1]]`, expected `[[0]]` |
| cirq-8525-bitmask | key/index remap | [Cirq #8525](https://github.com/quantumlib/Cirq/issues/8525) | FAIL `[[1]]`, expected `[[0]]` |
| cirq-8525-json-index | key/index remap | [Cirq #8525](https://github.com/quantumlib/Cirq/issues/8525) | FAIL `[[1]]`, expected `[[0]]` |
| stim-1143 | key/index remap | [Stim #1143](https://github.com/quantumlib/Stim/issues/1143) | FAIL `[[1]]`, expected `[[0]]` |
| stim-1136 | key/index remap | [Stim #1136](https://github.com/quantumlib/Stim/issues/1136) | FAIL `1`, expected last bit `0` |
| cirq-8528 | comparison rewritten | [Cirq #8528](https://github.com/quantumlib/Cirq/issues/8528) | FAIL `[[1]]`, expected `[[0]]` |
| cirq-8529 | comparison rewritten | [Cirq #8529](https://github.com/quantumlib/Cirq/issues/8529) | FAIL `[[0]]`, expected `[[1]]` |
| cirq-8530 | multi-bit condition | [Cirq #8530](https://github.com/quantumlib/Cirq/issues/8530) | FAIL, control bit 0 after export |
| qasm3-69 | register slice | [qasm3-import #69](https://github.com/Qiskit/qiskit-qasm3-import/issues/69) | FAIL `[]`, expected `[3, 2, 1, 0]` |
| stim-1145 | REPEAT dropped | [Stim #1145](https://github.com/quantumlib/Stim/issues/1145) | FAIL, `num_measurements=0` |
| stim-1132 | distance inside repeat | [Stim #1132](https://github.com/quantumlib/Stim/issues/1132) | UNAVAILABLE, no stimflow |
| stim-1135 | measurement width | [Stim #1135](https://github.com/quantumlib/Stim/issues/1135) | FAIL, `IndexError` |
| stim-1142 | control value dropped | [Stim #1142](https://github.com/quantumlib/Stim/issues/1142) | FAIL `[[0]]`, expected `[[1]]` |
| stim-1144 | confusion map dropped | [Stim #1144](https://github.com/quantumlib/Stim/issues/1144) | FAIL `[[1]]`; keep `[[0]]` or raise |
| stim-1137 | resumed shot counts | [Stim #1137](https://github.com/quantumlib/Stim/issues/1137) | FAIL, `hits=16`, `best=0.5` |
| stim-1146-grid | binomial lower edge | [Stim #1146](https://github.com/quantumlib/Stim/issues/1146) | FAIL, ratio `27.1728` (`low=1e-08`, exact `3.680150e-10`) |
| stim-1146-float32 | float32 upper half-width | [Stim #1146](https://github.com/quantumlib/Stim/issues/1146) | FAIL, half-width ratio `1.49671` |
| pymatching-193-d3 | correlated matching, watch only | [PyMatching #193](https://github.com/oscarhiggott/PyMatching/issues/193) | FAIL, 6 of 286 single faults; no comment drafted |

## Method

The eighteen fixtures do not decide pass or fail by sampling a noise distribution. The Sinter #1137 row uses `X_ERROR(1)`, batch size 16, a first collect of 16 shots, and a resumed collect of 32, so the expected counts are integers. The #1146 rows compare `fit_binomial` with a likelihood-ratio bisection at fixed `n`, `hits`, and `F`. The PyMatching row walks each decomposed error once. `after_clifford_depolarization=0.001` only builds the model; the check does not draw shots.

Three other commands compare a circuit that is not one of those rows. `stim-cirq-roundtrip` converts Stim to Cirq and back and compares detector count, observable count, and `detector_error_model(decompose_errors=False)` as mechanisms and probabilities (`math.isclose`, relative `1e-9`, absolute `1e-15`). With none of the noise names listed in `xcheck/stim_cirq.py`, it also compares one detector sample. Extra `TICK`s are allowed: `cirq_circuit_to_stim_circuit` documents that each Cirq moment becomes a `TICK`. Coordinates are not compared. `qasm3-roundtrip` compares gate sequence, qubit and clbit indexes, condition bits and values, and control-flow bodies after `qasm3.dumps` / `loads`. `if (c[0])` loads as `True`, treated as the same bit test as integer `1`. Unitary circuits are also compared with `Operator`; a circuit that measures skips that. `cirq-classical-control` compares records from the nested circuit, the unrolled circuit, and JSON. Field edits that do not move bits are notes.

Those three Cirq paths can share a bug and still agree. `xcheck.classical_ref` reads gates, keys, condition fields, and `CircuitOperation` `repetitions`, `measurement_key_map`, `repetition_ids`, `use_repetition_ids`, `parent_path`, and `qubit_map`. It applies the rules in that module (index 0 is earliest, bitmask integers are big-endian, symbols substitute by object identity, renames keep index, bitmask, target, and `equal_target`) and does not call `Condition.resolve`, `replace_key`, or `CircuitOperation.mapped_circuit`. `--oracle` compares each library path with that reference.

On the self-test, `cirq-classical-control builtin:8525` exited 0: the three paths agreed at `out=1`. With `--oracle` it exited 1: the reference recorded `out=0`. `examples/measure_then_x.json` uses index `-1` and is not the #8525 fixture.

README limits: the oracle accepts `X`, `CNOT`, measurement, `KeyCondition`, `BitMaskKeyCondition`, `SympyCondition`, and the `CircuitOperation` fields in `classical_ref.py`. Another gate makes `--oracle` an error. The tool does not fuzz, does not compare detector coordinates, and does not vendor Stim, Cirq, or Qiskit. `PASS` is agreement on this install for this fixture, not a proof for other circuits. `FAIL` says this fixture still disagrees, not that every version does.

## How to use

From a checkout:

```bash
pip install -e ".[stim,cirq,qiskit]"
python -m xcheck known
python -m xcheck stim-cirq-roundtrip examples/repetition_d3_r3.stim
python -m xcheck qasm3-roundtrip examples/bell.qasm
python -m xcheck cirq-classical-control examples/measure_then_x.json
python -m xcheck cirq-classical-control --oracle builtin:8525
```

The `stim` extra installs Stim, stimcirq, and Sinter. `cirq` and `qiskit` install the libraries those checks call. stimflow is used only by Stim #1132. pymatching and NumPy are used by the watch-only PyMatching #193 row and by `python -m xcheck distance`. The first run creates `mplconfig/` and `xdg_cache/` unless `MPLCONFIGDIR` and `XDG_CACHE_HOME` are set. For `known` and the conversion checks, exit 0 is a match, 1 is a mismatch, and 2 is a usage or runtime error. `distance` uses exit 0, 1, 2, 3, and 4 as defined in the README. `known` prints a table and one JSON object and exits 1 if any executed row is `FAIL`. From a checkout, Python puts `.` on the module path; `python -I` does not, so isolated mode needs an install.

On 2026-11-18, `examples/repetition_d3_r3.stim` exited 0 (8 detectors, 1 observable, detector samples equal). `examples/bell.qasm` exited 0 on the gate sequence; the operator was skipped because the file measures. `builtin:8525` exited 0 without `--oracle` and 1 with it. Those three example commands were not repeated for 0.3.0.

`.github/workflows/xcheck.yml` runs on push and pull request for Python 3.11 and 3.12, stable and `--pre`, with the extras plus pytest. It runs `pytest -q`, then `python -m xcheck known`. Exit 1 is written to `known-report.txt` and does not fail the job: a cited defect that is still present is the signal. Exit above 1 fails that cell. The artifact name is `known-py<version>-<track>`. The workflow file was read and not executed. As of 0.4.0 the install line includes the `distance` extra (NumPy and PyMatching) as well as `stim`, `cirq`, `qiskit`, and `test`. `tests/test_distance.py` does not import Cirq, Qiskit, sinter, or `tesseract_decoder`. The checks it runs need Stim, NumPy, and PyMatching. The workflow still does not install stimflow or `tesseract_decoder`. Stim #1132 stays `UNAVAILABLE` on a clean runner, and `python -m xcheck distance --decoder tesseract` stays `UNAVAILABLE` with exit 4 there too. The 2026-11-18 interpreter had no pytest. The 2026-11-19 run of the 0.3.0 tests reported 6 passed.

`python -m xcheck distance` is the 0.4.0 command. It is specified in the README section "Distance-preservation check". The figure it prints is a Stim search result (upper bound from the stated search). Statuses are `COUNTEREXAMPLE` (exit 1), `EXHAUSTIVE_NONE` (exit 0), `SAMPLED_NONE` (exit 3), and `UNAVAILABLE` (exit 4). Usage errors exit 2. The known-suite row `pymatching-193-d3` is unchanged: it still walks distance-3 rotated memory Z one fault at a time and remains `watch_only`.

To add a row: a short constructor in `xcheck/known/circuits.py`, a `check_*` in `suite.py` returning `_row` (id, issue URL, one sentence, the spec the expected value comes from, `PASS` or `FAIL`), and an entry in `all_checks`. Missing optional imports return `UNAVAILABLE`. Do not invent the circuit from the title. `tests/test_checks.py` asserts 18 cases, so update that count and the README id table. A row about someone else's report sets `watch_only` and does not draft a comment. Expected bits come from the cited spec or the published report, not from the library under test. If the three Cirq paths can share the bug, use the oracle.

## AI disclosure

The README states that the project was developed with AI coding assistants under the repository owner's direction, and that checks were reviewed against the cited documentation and issues. This note was drafted the same way from those files and `SELFTEST.md`. It adds no measurement.

## How to report a new difference

Reduce the circuit to a few gates, fixed bits, and one expected record. Include versions, the command, the exit code, and observed next to expected. If that fixture is already a row, add the version and the `known` line on that issue. Otherwise report to the project that owns the conversion: Cirq for conditions, JSON, and OpenQASM 2 export; Stim for Stim, stimcirq, and Sinter; `qiskit-qasm3-import` for an OpenQASM 3 import. State the documented rule, the smallest input, and the observation. Do not attribute a decision the issue does not contain. A new `qec-xcheck` row waits until that public report exists, and its expected value has to come from the specification, not from the failing library.
