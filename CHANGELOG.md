# Changelog

## 0.4.0 — 2026-11-19

- Add `python -m xcheck distance`. One fault is one DEM error mechanism after `detector_error_model(decompose_errors=True)`. One correlated fault counts as 1. Faults are not counted by decomposed graph edges. The distance line is a Stim search result (upper bound from the stated search).
- Statuses: `COUNTEREXAMPLE` (exit 1, with DEM text), `EXHAUSTIVE_NONE` (exit 0), `SAMPLED_NONE` (exit 3, `not a guarantee`, with the sampling ratio), `UNAVAILABLE` (exit 4). Usage errors exit 2. `--sample-pairs` returns only `SAMPLED_NONE` or `COUNTEREXAMPLE`.
- `toy-broken` flips the observable of DEM error mechanism 0 and delegates every other syndrome to PyMatching with correlations off. A PyMatching 2.4.0 count is a historical reproduction: a different version string skips that test instead of failing the run.
- A run with no counterexample says: no counterexample found within the stated scope (versions, noise model, enumerated weights).
- Each counterexample is labeled `DECODER_SPECIFIC`, `REFERENCE_ALSO_FAILS`, or `REFERENCE_UNAVAILABLE` by a second decode with ordinary PyMatching on the same DEM. The three counts are separate. Exit codes are unchanged. `REFERENCE_ALSO_FAILS` adds the hint that the truncation may exceed the true correction radius, because the Stim search result is an upper bound.
- Weight-2 enumeration counts pairs first. The default limit is 2000000. Above that limit, without `--sample-pairs`, the command does not enumerate pairs and returns `UNAVAILABLE` (exit 4), with the pair count, a time estimate from a local decoder timing, and suggested `--sample-pairs` / `--max-pairs` commands. `--max-pairs` raises the limit. The distance-5 rotated memory example has 1906128 pairs and is still enumerated.
- If `enable_correlations` raises `TypeError` or `AttributeError`, correlated matching returns `UNAVAILABLE` (exit 4) with the installed PyMatching version and the missing feature, and does not print a traceback.
- The `distance` extra requires `stim>=1.13`, `numpy>=1.21`, and `pymatching>=2.4.0`. Verified on stim 1.17.dev1793242987, pymatching 2.4.0, numpy 2.2.6, and Python 3.12. The NumPy floor is the 1.21 series used by the array operations in this check, not the machine that ran the verification.
- A counterexample found at any weight stays `COUNTEREXAMPLE` (exit 1), including when a later weight is not enumerated because the pair budget stopped it. The output keeps the counterexample lines and notes `weight 2: not enumerated (0 pairs checked, reason ...)`. That run is not rewritten as `UNAVAILABLE`.
- `decode_batch` must return shape `(samples, observables)` with values 0 or 1. Any other rank, shape, value, `None`, or exception is `DECODER_OUTPUT_INVALID` (exit 2). The check does not truncate, broadcast, or pad the array. A DEM with no observables, or with no error mechanisms, is a usage error (exit 2), not `EXHAUSTIVE_NONE`.
- The PyMatching #193 row compares the full one-observable prediction. An extra column or a value outside {0, 1} is `ERROR`, not a pass made by keeping the first entry.
- The README findings table lists each cited issue as `open (checked 2026-11-19)`.
- `docs/low-weight-vs-ler.md` states that the reweighting counts were reproduced with the PyMatching pull request 188 implementation at commit 176534d.
- `docs/low-weight-vs-ler.md` links the tqec gallery CNOT circuit (Apache-2.0, commit 7f767289). The file is not copied into this repository. A re-run on that file reported 15/4419 single-fault counterexamples for correlated matching and 0/4419 for ordinary matching.

## 0.3.0 — 2026-11-19

- Add Stim #1146 checks for the binomial lower-edge grid and the float32 upper half-width.
- Add a watch-only PyMatching #193 distance-3 correlated-matching row. A watch-only row records a problem reported by someone else. It does not draft a comment.
- The known table has a mark column. README lists each cited issue with `status: TBD`.

## 0.2.0 — 2026-11-18

- Command output, known-defect descriptions, expected results, and error text are English.
- `python -m xcheck known` prints one row per published conversion defect and a JSON summary.
- Checks cover a Stim/Cirq round trip, Cirq classical control with an optional independent oracle, and an OpenQASM 3 round trip.
- Cache directories are chosen at runtime from the environment or the working directory. No interpreter path is stored in the package.
