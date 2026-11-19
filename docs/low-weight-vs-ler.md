# Why a low-weight fault check and the logical error rate can disagree about a decoder change

A logical error rate counts shots that are logically wrong at one physical noise and one shot budget. A low-weight fault check asks whether any enumerated detector-error-model fault, of a stated weight, is decoded to the wrong observable. The two can move in opposite directions when the decoder changes. This note records that split for PyMatching's correlated matching, with one command for each count this repository can recompute. It does not recommend a decoder or a parameter.

## Versions

The commands below are qec-xcheck 0.4.0 (`version` in `pyproject.toml`, `__version__` in `xcheck/__init__.py`, and the `0.4.0` heading in `CHANGELOG.md`). Ordinary matching leaves correlations off. Correlated matching sets `enable_correlations=True` both when the matcher is built and when it decodes. Each distance command prints a `versions:` line. On Python 3.12.13 the recorded line was `numpy=2.2.6 pymatching=2.4.0 stim=1.17.dev1793242987 xcheck=0.4.0`. Another build can change the counts. Re-run, and keep the new line with the new counts. Exit codes are defined in the README.

## Two noise strengths

The family is `stim.Circuit.generated("surface_code:rotated_memory_z", ...)`, rounds equal to the distance unless a command says otherwise, noise only from Clifford-after depolarization. `examples/rotated_memory_z_d3_r3.stim` and `examples/rotated_memory_z_d5_r5.stim` use probability 0.001. The shot comparison uses 0.005. Do not read 527 versus 697 as a result on the 0.001 files, or the failure counts below as results at 0.005.

```bash
python examples/ler_compare.py
```

Defaults: distance 5, rounds 5, `p=0.005`, 200000 shots, sampler seed 1, one shared sample, Stim decomposition (`decompose_errors=True`, `flatten_loops=True`). Expected lines on the versions above:

```text
ordinary_logical_errors=697/200000 rate=0.003485 wilson95=[0.0032360915, 0.0037529815]
correlated_logical_errors=527/200000 rate=0.002635 wilson95=[0.0024196792, 0.0028694265]
paired_diff_correlated_minus_ordinary=-0.00085 wald95=[-0.0010959453, -0.00060405468] n10_correlated_only=230 n01_ordinary_only=400 n11_both=297
```

Wilson intervals are for each rate. The paired line is a Wald 95% interval for (correlated − ordinary) / shots. It is not an equivalence test. `--distance`, `--rounds`, `--p`, `--shots`, and `--seed` select another cell. Those expected counts are only the defaults.

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d3_r3.stim --decoder pymatching-correlated
```

Expected text includes `status: COUNTEREXAMPLE`, `single_failures: 6/286`, `pair_failures: not enumerated`, `attribution: DECODER_SPECIFIC=6 REFERENCE_ALSO_FAILS=0 REFERENCE_UNAVAILABLE=0`, and `exit: 1`. `--decoder pymatching` on the same file includes `single_failures: 0/286` and `exit: 0`.

```bash
python -m xcheck distance --circuit examples/rotated_memory_z_d5_r5.stim --decoder pymatching-correlated
```

Expected text includes `single_failures: 0/1953`, `pair_failures: 1173/1906128/1906128`, `DECODER_SPECIFIC=1173`, and `exit: 1`. Ordinary matching on that file includes `pair_failures: 0/1906128/1906128`. The README table records the same counts.

`DECODER_SPECIFIC` means ordinary PyMatching predicted the fault observable on the same DEM. `REFERENCE_ALSO_FAILS` means ordinary PyMatching missed it too. Repetition-code memory, distance 3, rounds 3, depolarization 0.001, at weight 2 is that case: the Stim search result is 3, so the derived cutoff is 1. `test_repetition_d3_overwide_cutoff_reference_also_fails` expects 70 pair failures out of 351, all `REFERENCE_ALSO_FAILS`, exit 1. Those rows match the weight that was asked for. They are not evidence that the decoder is worse than ordinary matching. `REFERENCE_UNAVAILABLE` means the second decode did not run. The labels do not change the counterexample rule.

The printed distance is the shorter positive length from the Stim search named in the output. A search can miss a shorter error, so the number is an upper bound, and `floor((that result - 1) / 2)` can be too large. The command never enumerates above weight 2. The second pass can push an edge weight so low that a fault ordinary matching corrects becomes a logical error ([PyMatching #193](https://github.com/oscarhiggott/PyMatching/issues/193)). This note does not re-derive those weights.

## A sample is not an exhaustive check

`EXHAUSTIVE_NONE` means every fault in the stated weight range was tested and none failed. It is not a claim about unlisted weights, and it is not a ranking of decoders. `SAMPLED_NONE` means `--sample-pairs` found no counterexample. The text includes `not a guarantee` and `pairs_tested/pair_space`. Covering every pair by requesting them all is still a sample result.

```bash
python -m xcheck distance --circuit examples/repetition_d5_r5.stim --decoder pymatching --sample-pairs 4
```

Expected text includes `pair_failures: 0/4/4465`, `sampling ratio: 4/4465`, `not a guarantee`, and `exit: 3`.

Weight 3 and above is not enumerated. One fault is one `error` instruction after `decompose_errors=True`. A `^` splits that instruction into edges and does not add a fault. The command adds no noise channel. The example files are not the p=0.005 sample.

## Which number to read

Read the logical error rate for average behavior at a stated noise and shot budget. The 527-versus-697 row can favor correlated matching while the p=0.001 check lists 6 single-fault misses and 1173 pair misses. Read the low-weight check for the low-noise end, for rare faults, or when every enumerated fault up to a stated weight must be corrected. `DECODER_SPECIFIC` supports "this decoder missed a fault the ordinary matcher corrected." `REFERENCE_ALSO_FAILS` means the requested weight may sit past the radius implied by a loose search.

Scaling that second pass shows the same kind of split. [PyMatching pull request 188](https://github.com/oscarhiggott/PyMatching/pull/188) discusses `reweighting_strength`. PyMatching 2.4.0 has no such parameter. The `s` counts below are one reimplementation on the versions above: the conditional probability is multiplied by `s`, capped at 1/2, and the edge weight is replaced only when the new weight is lower. The same counts were reproduced with the pull request's own implementation at commit 176534d (see https://github.com/oscarhiggott/PyMatching/pull/188#issuecomment-7010012455). This tree does not contain that reimplementation, so these counts are not the output of a command here. No value of `s` is recommended.

On rotated memory Z, distance 5, p=0.005, exhaustive pair failures at `s=1 / 0.5 / 0.2 / 0.1 / 0.05` were 990 / 389 / 76 / 4 / 0 out of 1906128. Logical errors on the same five values, 200000 shots, seed 1, were 527 / 474 / 522 / 603 / 664, against 697 for ordinary matching. `s=1` matched native correlated matching (990 and 527, the same 527 as `ler_compare.py`). At `s=0.05` the logical-error count was 664, not the native 527. That is one measured tradeoff on this cell.

On rotated memory Z at distance 3, `s=0.2` had 0 single-fault failures out of 286 at p=0.001, 0.002, and 0.005, where native correlated matching had 6, 6, and 4. Logical-error counts at `s=0.2` on those three cells were lower than native correlated matching. Lower on these cells is not "equally good."

On the five gallery circuits from tqec `7f767289badb6e975de00da64e69f31356fe4bc5` (memory, move_rotation, cnot, three_cnots, steane_encoding), `s=0.2` left single-fault failures 2, 0, 0, 0, and 0. A paired Wald 95% interval for (`s=0.2` minus native correlated matching), each circuit's own noise, 100000 shots, seed 20261119, did not show significantly more logical errors on any of the five. A comparison that did not flag a significant increase is not "equally good," and it is not a test of whether two confidence intervals overlap. `EXHAUSTIVE_NONE` is not that sentence either. It only means that no counterexample was found inside the stated scope.

## A circuit from tqec

tqec is Apache-2.0. This repository does not contain its circuits. Commit `7f767289badb6e975de00da64e69f31356fe4bc5` has `docs/media/gallery/cnot/circuit.stim` at <https://github.com/tqec/tqec/blob/7f767289badb6e975de00da64e69f31356fe4bc5/docs/media/gallery/cnot/circuit.stim>. Download that file, then run:

```bash
python -m xcheck distance --circuit circuit.stim --decoder pymatching-correlated
python -m xcheck distance --circuit circuit.stim --decoder pymatching
```

On the versions named above, correlated matching printed `single_failures: 15/4419`, `pair_failures: not enumerated`, and `exit: 1`. Ordinary matching printed `single_failures: 0/4419`, `pair_failures: not enumerated`, and `exit: 0`. The Stim search result was 3, so only weight 1 was enumerated. Both commands use the native matcher (`enable_correlations` on or off). The `s=0.2` counts later in this note are the separate reimplementation described above.

Prepared with AI assistance; directed and reviewed by the repository owner.
