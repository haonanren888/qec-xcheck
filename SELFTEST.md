# Self-test (2026-11-19)

Interpreter: the main tracking environment, Python 3.12.13. Cache directories were the task directory's `mplconfig/` and `xdg_cache/`, not paths stored in the package. No packages were installed.

Command: `python -m xcheck known` from this checkout, so the working directory is on the module path. Exit 1.

Versions: cirq `1.8.0.dev20261117194631`, stim/stimcirq/sinter `1.17.dev1793242987`, qiskit `2.6.2`, pymatching `2.4.0`, numpy `2.2.6`, pytest `9.2.0`. stimflow: not installed.

Counts: PASS 0, FAIL 17, UNAVAILABLE 1, ERROR 0. Eighteen rows. `watch_only` is only `pymatching-193-d3`.

| id | status | observed |
| --- | --- | --- |
| cirq-8525 | FAIL | [[1]] |
| cirq-8525-bitmask | FAIL | [[1]] |
| cirq-8525-json-index | FAIL | [[1]] |
| cirq-8528 | FAIL | [[1]] |
| cirq-8529 | FAIL | [[0]] |
| cirq-8530 | FAIL | control bit 0 after export |
| qasm3-69 | FAIL | [] |
| stim-1136 | FAIL | 1 |
| stim-1142 | FAIL | [[0]] |
| stim-1143 | FAIL | [[1]] |
| stim-1144 | FAIL | [[1]] |
| stim-1145 | FAIL | num_measurements=0 sample=[] |
| stim-1135 | FAIL | IndexError: index 2 is out of bounds for axis 1 with size 2 |
| stim-1137 | FAIL | shots=32 errors=32 discards=0 obs_mistake_mask=E_=16 best=0.5 |
| stim-1132 | UNAVAILABLE | No module named 'stimflow' |
| stim-1146-grid | FAIL | low=1e-08 exact=3.680150e-10 ratio=27.1728 |
| stim-1146-float32 | FAIL | high=0.10005278236 exact=0.10003527 half_ratio=1.49671 |
| pymatching-193-d3 | FAIL, watch_only | single_fault_failures=6 total=286 |

pytest: `python -m pytest -q -p no:cacheprovider` exited 0, 6 passed in 4.57s. The three example-file commands from the 2026-11-18 note were not repeated.

The GitHub Actions workflow was read and not run. At that 0.3.0 reading it did not install stimflow or pymatching.

## Distance command (0.4.0 semantic revision)

Same interpreter, still no install. Isolated mode does not put the checkout on `sys.path`. The test process inserted only this checkout before importing pytest. Versions: xcheck `0.4.0`, stim `1.17.dev1793242987`, pymatching `2.4.0`, numpy `2.2.6`.

Final `pytest -q -p no:cacheprovider`: 15 passed in 5.02s. That includes the six 0.3.0 tests and the historical PyMatching 2.4.0 counts (correlated d=3 is 6, correlated d=5 pairs are 1173). A different `pymatching.__version__` skips those counts and prints `behavior may have changed; re-run and explain`.

The distance line is a Stim search result (upper bound from the stated search). One fault is one DEM error mechanism after `decompose_errors=True`.

| Circuit | Decoder | Search result | Checked weight | Result |
| --- | --- | ---: | ---: | --- |
| rotated memory Z | pymatching | 3 | 1 | EXHAUSTIVE_NONE, 0/286 singles, exit 0, 0.184s |
| rotated memory Z | pymatching-correlated | 3 | 1 | COUNTEREXAMPLE, 6/286 singles, exit 1, 0.187s |
| rotated memory Z | toy-broken | 3 | 1 | COUNTEREXAMPLE, 1/286 singles, DEM `error(0.000266738) D0`, exit 1, 0.183s |
| rotated memory Z | pymatching | 5 | 2 | EXHAUSTIVE_NONE, 0/1953 and 0/1906128, exit 0, 1.463s |
| rotated memory Z | pymatching-correlated | 5 | 2 | COUNTEREXAMPLE, 0/1953 and 1173/1906128, exit 1, 3.712s |
| repetition | pymatching | 5 | 2 | EXHAUSTIVE_NONE, 0/95 and 0/4465, exit 0, 0.192s |
| repetition | pymatching-correlated | 5 | 2 | EXHAUSTIVE_NONE, 0/95 and 0/4465, exit 0, 0.188s |
| repetition, `--sample-pairs 4` | pymatching | 5 | 2 | SAMPLED_NONE, ratio 4/4465, `not a guarantee`, exit 3, 0.187s |

A repetition-code circuit with distance argument 3 and `--max-weight 2` still reproduces plain 70/351 and correlated 69/351 when PyMatching is 2.4.0. The workflow file installs the `distance` extra. It was not executed. No counterexample found within the stated scope is the wording used when the enumerated weights had no hit. That sentence is not a claim outside those versions, that noise model, and those weights.
