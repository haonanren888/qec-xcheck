# qec-xcheck

One distance-3 rotated-memory circuit, two decoders. Ordinary matching misses none of the 286 single faults. Correlated matching misses 6.

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching
```

`single_failures: 0/286`, `status: EXHAUSTIVE_NONE`, exit 0.

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching-correlated
```

`single_failures: 6/286`, `status: COUNTEREXAMPLE`, exit 1.

Your own circuit:

```bash
python -m xcheck distance --circuit your.stim --decoder pymatching
```

Your own decoder. `factory(dem)` returns an object with `decode_batch(dets)`, or the factory itself is that function. `dets` has shape `(shots, detectors)`. The return value must be two-dimensional, with one row per input sample and one column per DEM observable, and every value must be 0 or 1. Anything else — a different rank, a different shape, a value other than 0 or 1, `None`, or an exception — is `DECODER_OUTPUT_INVALID` (exit 2). The text states the expected shape and the actual shape. The check does not truncate, broadcast, or fill missing entries with zeros.

```bash
python -m xcheck distance --circuit your.stim --decoder custom:module:factory
```

Verified versions: stim 1.17.dev1793242987, pymatching 2.4.0, numpy 2.2.6, Python 3.12.

```bash
pip install -e ".[stim,cirq,qiskit,distance]"
```

The `distance` extra installs `stim>=1.13`, `numpy>=1.21`, and `pymatching>=2.4.0`.

| Exit | Meaning |
| ---: | --- |
| 0 | `EXHAUSTIVE_NONE`, or a non-distance check matched |
| 1 | `COUNTEREXAMPLE`, or a non-distance check did not match |
| 2 | usage or runtime error, including `DECODER_OUTPUT_INVALID` |
| 3 | `SAMPLED_NONE` (`not a guarantee`) |
| 4 | `UNAVAILABLE` or `TIMEOUT` |

# qec-xcheck

QEC toolchains convert the same circuit between Stim, Cirq, and OpenQASM. A conversion can finish without an exception and still change a detector, an observable, a measurement bit, or a classical condition. `qec-xcheck` runs small, cited checks and reports that kind of silent change.

For background, the eighteen public cases and the method, see [docs/TECHNICAL_NOTE.md](docs/TECHNICAL_NOTE.md).

The import package is `xcheck`.

## Install

From a checkout:

```bash
pip install -e ".[stim,cirq,qiskit,distance]"
```

The `stim` extra installs Stim, stimcirq, and sinter. The `cirq` and `qiskit` extras install the libraries those checks call. The `distance` extra installs Stim, NumPy, and PyMatching for `python -m xcheck distance` (`stim>=1.13`, `numpy>=1.21`, `pymatching>=2.4.0`). Verified versions: stim 1.17.dev1793242987, pymatching 2.4.0, numpy 2.2.6, Python 3.12. `stimflow` is optional and is used only by the Stim #1132 row. `tesseract_decoder` is optional and is not part of an extra. `pymatching` is also the library used by the watch-only PyMatching #193 row.

## Commands

```bash
python -m xcheck known
python -m xcheck stim-cirq-roundtrip examples/repetition_d3_r3.stim
python -m xcheck qasm3-roundtrip examples/bell.qasm
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching-correlated
```

`known`, `stim-cirq-roundtrip`, `qasm3-roundtrip`, and `cirq-classical-control` exit `0` when the check matches, `1` when it does not, and `2` on a usage or runtime error. `known` prints a table and then one JSON object. It exits `1` when any executed row is `FAIL`.

`distance` does not use that scale. It exits `0` for `EXHAUSTIVE_NONE`, `1` for `COUNTEREXAMPLE`, `2` on a usage error, `3` for `SAMPLED_NONE`, and `4` for `UNAVAILABLE`. The next section defines those words.

From a checkout, a normal `python -m xcheck` finds this package because Python puts the working directory on the module path. Isolated mode (`python -I`) drops `PYTHONPATH` and does not put the working directory on `sys.path`. Insert the checkout and the directory that contains a `custom:` module into `sys.path` before importing them. See the custom-decoder section below.

`PASS` means this install matches the cited spec. `FAIL` means the published defect is still present. `UNAVAILABLE` means a saved reproduction needs a component this interpreter does not have.

A row marked `watch_only` records a problem reported by someone else. The suite observes the current result and does not draft a comment. The mark does not change the exit rule: a `FAIL` on that row still makes `known` exit 1.

## Distance-preservation check

`distance` compares a decoder's observable prediction with the observable on enumerated DEM faults from one Stim file. A hit is a counterexample on that fault. A miss is not a proof outside the stated scope.

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching-correlated
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder toy-broken
python -m xcheck distance --circuit examples/rotated_memory_z_d5_r5.stim --decoder pymatching
python -m xcheck distance --circuit examples/rotated_memory_z_d5_r5.stim --decoder pymatching-correlated
python -m xcheck distance --circuit examples/repetition_d5_r5.stim --decoder pymatching
python -m xcheck distance --circuit examples/repetition_d5_r5.stim --decoder pymatching --sample-pairs 4
```

### What is counted

The command builds `detector_error_model(decompose_errors=True)`. One fault is one DEM `error` instruction. One correlated fault counts as 1. A `^` separator only splits that instruction into edges; the fault syndrome and the fault observable are the parity of every target. Faults are not counted by decomposed graph edges. Weight 2 is an unordered pair of those faults, combined by parity. This is not two Pauli errors inserted into the circuit. Weights above 2 are outside this command's enumeration.

The noise model is whatever error instruction the circuit file already contains. This command does not add a channel. JSON field `stated_scope.noise_model` records that source and the instruction counts. `stated_scope.observable_count` is the DEM observable count. `stated_scope.distance.search_params` is the argument list passed to Stim.

### Distance line

The distance line is `Stim search result (upper bound from the stated search)`. The number is the shorter positive length from `shortest_graphlike_error(canonicalize_circuit_errors=True)` and `search_for_undetectable_logical_errors` with the parameters in the JSON. A truncated search can miss a shorter error, so the number is an upper bound from that search. The enumerated cutoff is `floor((that result - 1) / 2)`, and this command caps enumeration at weight 2. `--max-weight 1` or `--max-weight 2` enumerates that weight instead.

### Statuses

| Status | Exit | When |
| --- | ---: | --- |
| `COUNTEREXAMPLE` | 1 | At least one enumerated fault disagreed. JSON `counterexamples` holds up to eight DEM texts, and the text output prints those lines. |
| `EXHAUSTIVE_NONE` | 0 | The stated weight range was fully enumerated and no counterexample was found. The text is `no counterexample found within the stated scope (versions, noise model, enumerated weights)`. |
| `SAMPLED_NONE` | 3 | `--sample-pairs` was set, the sample contained no counterexample, and the text includes `not a guarantee` plus the sampling ratio `pairs_tested/pair_space`. |
| `UNAVAILABLE` | 4 | The check could not be evaluated: missing `stim`, `numpy`, `pymatching`, or `tesseract_decoder`; correlated matching does not provide `enable_correlations`; Stim returned no logical-error length and neither `--max-weight` nor `--sample-pairs` was set; the derived cutoff is 0 because the Stim search result is below 3; a `custom:` module failed to import or its factory raised; or the weight-2 pair count is above the limit, `--sample-pairs` was not set, and no counterexample was found at a lower weight. A cutoff of 0 says `0 faults tested; Stim search result is <n>, so the derived cutoff is 0; use --max-weight 1 to test single faults` and does not use the no-counterexample sentence. The default pair limit is 2000000. `--max-pairs N` raises it. The pair-limit message gives the pair count, an estimated exhaustive time from a local timing of the decoder, and suggested `--sample-pairs` and `--max-pairs` commands. If a lower weight already produced a counterexample, the status stays `COUNTEREXAMPLE` and the text notes `weight 2: not enumerated (0 pairs checked, reason ...)`. |
| `TIMEOUT` | 4 | `--timeout SECONDS` expired before the requested weights finished, and no counterexample had been found. The text does not say the scope had no counterexample. A counterexample found before the deadline stays `COUNTEREXAMPLE` (exit 1), with its lines kept. |
| `DECODER_OUTPUT_INVALID` | 2 | `decode_batch` returned `None`, the wrong rank, the wrong shape, a value other than 0 or 1, or raised. The message contains `expected (rows, observables) got ...`. |

Usage errors exit 2: a bad argument, `--max-weight` outside 1 or 2, `--timeout` that is not a positive number of seconds, a missing or unreadable circuit file, a `custom:` spec that is not `custom:module:function`, a DEM with no observables, or a DEM with no error mechanisms. A custom module that cannot be imported, or a factory that raises while it is built, is `UNAVAILABLE` (exit 4); the message keeps the exception type and the original text. `DECODER_OUTPUT_INVALID` is also exit 2. `--sample-pairs` never exits 0. It is `SAMPLED_NONE` or `COUNTEREXAMPLE` only, including when the requested sample happens to cover every pair. `--json` prints one JSON object. When weight 2 is not part of the run, JSON `pairs_tested` and `pair_failures` are null and `enumeration_note` is set. The text line stays `pair_failures: not enumerated`. The pair-limit stop is separate: `pairs_tested` is 0 and `pair_failures` is null, with the reason the pair space was above the limit. `--help` exits 0.

`toy-broken` is a built-in test decoder. It decodes with PyMatching, correlations off, then replaces the observable of DEM error mechanism 0 with that observable flipped on the first bit. Every other syndrome keeps the PyMatching prediction. A run that does not report `COUNTEREXAMPLE` for `toy-broken` is a broken check.

### Counterexample attribution

Every counterexample, single fault or fault pair, is decoded once more with ordinary PyMatching on the same DEM (`Matching.from_detector_error_model` with correlations left off). The three labels are counted separately in the text line `attribution:` and in the JSON object `attribution`. They do not change the exit code. `COUNTEREXAMPLE` is still exit 1 whether the reference agrees or not.

| Label | Meaning |
| --- | --- |
| `DECODER_SPECIFIC` | Ordinary PyMatching predicts the fault observable. The miss belongs to the decoder under test. |
| `REFERENCE_ALSO_FAILS` | Ordinary PyMatching misses it too. The enumerated weight may sit past the true correction radius: the cutoff is computed from a Stim search result, and that result is an upper bound. The output then includes `The truncation may exceed the true correction radius (the Stim search result is an upper bound).` |
| `REFERENCE_UNAVAILABLE` | Ordinary PyMatching could not be constructed or called. The counterexample is still reported. |

When the decoder under test is already `pymatching`, the reference is that same decoder, so each of its counterexamples is `REFERENCE_ALSO_FAILS`. One such case is repetition-code memory, distance 3, rounds 3, `after_clifford_depolarization=0.001`, with `--max-weight 2`. The Stim search result there is 3, so the derived cutoff is weight 1. Weight 2 is outside that cutoff. How to read a low-weight miss next to a logical error rate is discussed in [docs/low-weight-vs-ler.md](docs/low-weight-vs-ler.md).

### Recorded results

The three example files were written from `stim.Circuit.generated` with `rounds` equal to the distance argument below and `after_clifford_depolarization=0.001`:

```python
stim.Circuit.generated("surface_code:rotated_memory_z", distance=3, rounds=3, after_clifford_depolarization=0.001)
stim.Circuit.generated("surface_code:rotated_memory_z", distance=5, rounds=5, after_clifford_depolarization=0.001)
stim.Circuit.generated("repetition_code:memory", distance=5, rounds=5, after_clifford_depolarization=0.001)
```

The table is a historical reproduction on PyMatching `2.4.0` and Stim `1.17.dev1793242987`. A different PyMatching version is not a failure of this package; re-run and explain the new counts. Plain PyMatching builds and decodes with correlations off. Correlated PyMatching sets `enable_correlations=True` both when the matcher is built and when it decodes. Upstream discussion: [PyMatching #193](https://github.com/oscarhiggott/PyMatching/issues/193) and [PyMatching #188](https://github.com/oscarhiggott/PyMatching/issues/188).

| Decoder | Circuit | Stim search result | Enumerated weight | Recorded outcome |
| --- | --- | ---: | ---: | --- |
| pymatching | rotated memory Z | 3 | 1 | no counterexample found within the stated scope (versions, noise model, enumerated weights); 0 of 286 single faults |
| pymatching | rotated memory Z | 5 | 2 | no counterexample found within the stated scope (versions, noise model, enumerated weights); 0 of 1953 singles and 0 of 1906128 pairs |
| pymatching-correlated | rotated memory Z | 3 | 1 | 6 single-fault counterexamples out of 286 |
| pymatching-correlated | rotated memory Z | 5 | 2 | 1173 pair counterexamples out of 1906128; 0 of 1953 singles |

On that same noise, repetition-code memory whose Stim search result is 5 enumerates weight 2. In that historical run, both decoders had no counterexample on all 95 singles and all 4465 pairs. `examples/repetition_d5_r5.stim` is that circuit. The wording for that outcome is: no counterexample found within the stated scope (versions, noise model, enumerated weights).

`--max-weight 2` on the search-result-3 file also checks pairs. Those pairs are outside the cutoff derived from that search result. A counterexample there is still a `COUNTEREXAMPLE` for the weight you asked to enumerate. The default command stops at weight 1 when the Stim search result is 3.

`--sample-pairs 4` on `examples/repetition_d5_r5.stim` with plain PyMatching asks for four pairs out of 4465. With no hit, the status is `SAMPLED_NONE`, the exit code is 3, and the text includes `not a guarantee` and the ratio `4/4465`.

Before a weight-2 enumeration the command counts pairs. `examples/rotated_memory_z_d5_r5.stim` has 1906128 pairs, which is under the default limit of 2000000, so that file is still fully enumerated. A larger pair count, with no `--sample-pairs`, exits 4 and does not start the pair enumeration. `--max-pairs` set to at least that count enumerates it. `--sample-pairs` still samples when the count is above the limit.

A custom decoder is a callable `factory(dem)` that returns an object with `decode_batch(dets)`. `dets` has shape `(shots, detectors)`. The array it returns must have shape `(shots, observables)` and values 0 or 1 only. A returned function is used as `decode_batch` directly. A wrong return is `DECODER_OUTPUT_INVALID` (exit 2), with the expected shape and the actual shape. The check does not truncate, broadcast, or pad.

```python
class MyDecoder:
    def __init__(self, dem):
        self.dem = dem

    def decode_batch(self, dets):
        raise NotImplementedError

def factory(dem):
    return MyDecoder(dem)
```

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder custom:my_decoder:factory
```

`python -I` does not put the working directory or `PYTHONPATH` on `sys.path`, so `custom:module:factory` cannot see `module` until that process inserts the directory which contains it:

```python
import sys
sys.path.insert(0, "path/to/checkout")
sys.path.insert(0, "path/to/custom/parent")
from xcheck.__main__ import main
raise SystemExit(main(["distance", "--circuit", "your.stim", "--decoder", "custom:module:factory"]))
```

If that import fails, the status is `UNAVAILABLE` (exit 4). The message names the module. When the interpreter is in isolated mode, it also says that `python -I` left the module off `sys.path`.

A decoder that returns `bool` has to be cast to `uint8` before this check will accept it:

```python
import numpy as np

def factory(dem):
    decoder = build_bool_decoder(dem)

    def decode_batch(dets):
        return np.asarray(decoder.decode_batch(dets), dtype=np.uint8)

    return decode_batch
```

Sinter's bit-packed decoders take packed detector bytes and return packed observable bytes. `sinter.BUILT_IN_DECODERS["fusion_blossom"]` is one entry point. Split those bytes into one column per observable:

```python
import numpy as np
from sinter import BUILT_IN_DECODERS

def factory(dem):
    compiled = BUILT_IN_DECODERS["fusion_blossom"].compile_decoder_for_dem(dem=dem)

    def decode_batch(dets):
        dets = np.atleast_2d(np.asarray(dets, dtype=np.uint8))
        packed = np.packbits(dets, axis=1, bitorder="little")
        predicted = compiled.decode_shots_bit_packed(bit_packed_detection_event_data=packed)
        columns = np.unpackbits(np.asarray(predicted, dtype=np.uint8), axis=1, bitorder="little")
        return np.ascontiguousarray(columns[:, : dem.num_observables])

    return decode_batch
```

## Known defects

```text
| id | status | issue | summary | expected | observed | mark |
| --- | --- | --- | --- | --- | --- | --- |
| cirq-8525 | FAIL | https://github.com/quantumlib/Cirq/issues/8525 | ... | out == [[0]] | [[1]] | |
| pymatching-193-d3 | ... | https://github.com/oscarhiggott/PyMatching/issues/193 | ... | single-fault failure count == 0 | ... | watch_only |
```

The status column is the result on your install. While the cited defects are still present, `known` exits 1. The 0.2.0 suite, without `stimflow`, reported 14 `FAIL`, 1 `UNAVAILABLE` (Stim #1132), and 0 `ERROR` across 15 rows. One 0.3.0 run without `stimflow`, with PyMatching present, reported 17 `FAIL`, 1 `UNAVAILABLE` (Stim #1132), and 0 `ERROR` across 18 rows. The PyMatching row was `FAIL` and `watch_only`.

The rows and the issues they cite:

| id | What a PASS requires | Issue |
| --- | --- | --- |
| cirq-8525 | `KeyCondition` index 0 inside a `CircuitOperation` reads the earliest measurement | https://github.com/quantumlib/Cirq/issues/8525 |
| cirq-8525-bitmask | `BitMaskKeyCondition.replace_key` keeps bitmask, target, and index | https://github.com/quantumlib/Cirq/issues/8525 |
| cirq-8525-json-index | JSON round-trips `KeyCondition.index` | https://github.com/quantumlib/Cirq/issues/8525 |
| cirq-8528 | A positive symbol is false after substituting measurement 0 | https://github.com/quantumlib/Cirq/issues/8528 |
| cirq-8529 | Swapping measurement keys keeps both sides of the comparison | https://github.com/quantumlib/Cirq/issues/8529 |
| cirq-8530 | An OpenQASM 2 export keeps a multi-bit `m == 2` branch | https://github.com/quantumlib/Cirq/issues/8530 |
| qasm3-69 | The inclusive slice `q[3:-1:0]` is four X gates | https://github.com/Qiskit/qiskit-qasm3-import/issues/69 |
| stim-1136 | `REPEAT` export keeps `measurement_key_map` | https://github.com/quantumlib/Stim/issues/1136 |
| stim-1142 | `control_values=(0,)` acts when the control qubit is 0 | https://github.com/quantumlib/Stim/issues/1142 |
| stim-1143 | stimcirq treats `KeyCondition` index 0 as the earliest measurement | https://github.com/quantumlib/Stim/issues/1143 |
| stim-1144 | Measurement confusion is kept, or the conversion raises | https://github.com/quantumlib/Stim/issues/1144 |
| stim-1145 | An outer `repetitions=1` keeps the inner `REPEAT` | https://github.com/quantumlib/Stim/issues/1145 |
| stim-1135 | Each multi-qubit Pauli measurement contributes one bit | https://github.com/quantumlib/Stim/issues/1135 |
| stim-1137 | A resumed sinter plot counts all 32 shots in the numerator | https://github.com/quantumlib/Stim/issues/1137 |
| stim-1132 | A distance check rejects a distance-1 error inside `repeat` | https://github.com/quantumlib/Stim/issues/1132 |
| stim-1146-grid | With one hit, `fit_binomial`'s lower edge stays within 1.05 of the exact likelihood-ratio edge | https://github.com/quantumlib/Stim/issues/1146 |
| stim-1146-float32 | A large-sample float32 log-likelihood does not stretch the upper half-width past 1.05 times exact | https://github.com/quantumlib/Stim/issues/1146 |
| pymatching-193-d3 | Correlated matching corrects every single fault on distance-3 rotated memory Z. Watch only: no comment is drafted | https://github.com/oscarhiggott/PyMatching/issues/193 |

## Findings so far

Each link below is an issue URL cited by `xcheck/known/suite.py`. Each cited issue was open (checked 2026-11-19).

| issue | checks in this suite | status |
| --- | --- | --- |
| https://github.com/quantumlib/Cirq/issues/8525 | cirq-8525, cirq-8525-bitmask, cirq-8525-json-index | open (checked 2026-11-19) |
| https://github.com/quantumlib/Cirq/issues/8528 | cirq-8528 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Cirq/issues/8529 | cirq-8529 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Cirq/issues/8530 | cirq-8530 | open (checked 2026-11-19) |
| https://github.com/Qiskit/qiskit-qasm3-import/issues/69 | qasm3-69 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1136 | stim-1136 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1142 | stim-1142 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1143 | stim-1143 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1144 | stim-1144 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1145 | stim-1145 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1135 | stim-1135 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1137 | stim-1137 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1132 | stim-1132 | open (checked 2026-11-19) |
| https://github.com/quantumlib/Stim/issues/1146 | stim-1146-grid, stim-1146-float32 | open (checked 2026-11-19) |
| https://github.com/oscarhiggott/PyMatching/issues/193 | pymatching-193-d3 (watch_only; someone else's report, observed only) | open (checked 2026-11-19) |

## Independent oracle

```bash
python -m xcheck cirq-classical-control --oracle builtin:8525
```

`--oracle` compares the nested circuit, the unrolled circuit, and the JSON round trip with `xcheck.classical_ref`. That reference reads gates, keys, and `CircuitOperation` fields and evaluates conditions from the Cirq documentation. It does not call `Condition.resolve`, `replace_key`, or `CircuitOperation.mapped_circuit`.

Without `--oracle`, those three simulations can share one bug and still agree. `builtin:8525` is that case: the three paths agree, and `--oracle` reports a mismatch. `examples/measure_then_x.json` is a separate circuit whose default index is the latest measurement.

## Other checks

`stim-cirq-roundtrip` compares detector count, observable count, and `detector_error_model(decompose_errors=False)` as error mechanisms and probabilities. A circuit with no noise also compares one deterministic detector sample. Extra `TICK`s are not a failure: `cirq_circuit_to_stim_circuit` documents that each Cirq moment becomes a `TICK`.

`qasm3-roundtrip` compares the gate sequence, qubit and clbit indexes, and classical condition bits and values. A one-bit condition written as `if (c[0])` loads as `True`, which is the same bit test as the integer `1`. Unitary circuits are also compared with `qiskit.quantum_info.Operator`.

The first run creates `mplconfig/` and `xdg_cache/` in the working directory unless `MPLCONFIGDIR` and `XDG_CACHE_HOME` are already set.

## Limitations

- The oracle accepts `X`, `CNOT`, measurement, `KeyCondition`, `BitMaskKeyCondition`, `SympyCondition`, and the `CircuitOperation` fields implemented in `xcheck/classical_ref.py`. Other gates make `--oracle` return an error.
- Stim #1132 is `UNAVAILABLE` when `stimflow` is not installed. The suite does not invent a reproduction from an issue title.
- PyMatching #193 is `watch_only`. The row records the result and does not draft a comment. It is `UNAVAILABLE` when `pymatching`, NumPy, or Stim is missing.
- `distance` enumerates DEM error mechanisms after `decompose_errors=True`. One correlated fault counts as 1. It does not count decomposed graph edges, and it does not cover every physical error outside that model. `--sample-pairs` prints `not a guarantee` when it finds no counterexample. The distance line is a Stim search result (upper bound from the stated search).
- The tool does not fuzz, does not compare detector coordinates, and does not vendor Stim, Cirq, or Qiskit.
- A `FAIL` row is a defect that is still present. It is not a crash of this package.

## AI statement

This project was developed with AI coding assistants under the direction of the repository owner; all checks were reviewed against the cited documentation and issues.

## License

Apache License 2.0. See [LICENSE](LICENSE).
