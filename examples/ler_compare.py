#!/usr/bin/env python3
"""Logical-error counts for ordinary matching and correlated matching.

Both decoders see one shared sample of
``surface_code:rotated_memory_z``. Defaults are distance 5, 5 rounds,
``after_clifford_depolarization=0.005``, 200000 shots, and sampler seed 1.
The detector error model is Stim's decomposition (``decompose_errors=True``,
``flatten_loops=True``). Ordinary matching leaves correlations off.
Correlated matching sets ``enable_correlations=True`` when the matcher is
built and when it decodes.

The paired interval is a Wald 95% interval for
(correlated logical errors - ordinary logical errors) / shots
on that shared sample. It is not an equivalence test.
"""

from __future__ import annotations

import argparse
import math

import numpy as np
import pymatching
import stim
from pymatching import Matching

Z95 = 1.959963984540054


def wilson(k: int, n: int) -> tuple[float, float, float]:
    if n <= 0:
        raise SystemExit("shots must be positive")
    phat = k / n
    z2 = Z95 * Z95
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    margin = Z95 * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n)) / denom
    return phat, max(0.0, center - margin), min(1.0, center + margin)


def as_obs(pred, nshots: int, nobs: int) -> np.ndarray:
    pred = np.asarray(pred, dtype=np.uint8)
    if pred.ndim == 1:
        pred = pred.reshape(-1, 1)
    if pred.shape != (nshots, nobs) and pred.shape[1] < nobs:
        raise SystemExit(f"prediction width {pred.shape[1]} < {nobs}")
    return pred[:, :nobs]


def paired_wald(wrong_a: np.ndarray, wrong_b: np.ndarray) -> tuple[float, float, float, int, int, int]:
    """Difference a minus b. Returns diff, lo, hi, n10, n01, n11."""
    n = int(wrong_a.shape[0])
    n10 = int(np.count_nonzero(wrong_a & ~wrong_b))
    n01 = int(np.count_nonzero(~wrong_a & wrong_b))
    n11 = int(np.count_nonzero(wrong_a & wrong_b))
    diff = (n10 - n01) / n
    p10 = n10 / n
    p01 = n01 / n
    var = (p10 + p01 - (p10 - p01) ** 2) / n
    se = math.sqrt(var) if var > 0.0 else 0.0
    return diff, diff - Z95 * se, diff + Z95 * se, n10, n01, n11


def fmt(x: float) -> str:
    return f"{x:.8g}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--p", type=float, default=0.005)
    parser.add_argument("--shots", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.distance < 1 or args.rounds < 1 or args.shots < 1 or not (0.0 < args.p < 1.0):
        raise SystemExit("distance, rounds, and shots must be >= 1, and p must be in (0, 1)")

    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=args.distance,
        rounds=args.rounds,
        after_clifford_depolarization=args.p,
    )
    dem = circuit.detector_error_model(decompose_errors=True, flatten_loops=True)
    dets, obs = circuit.compile_detector_sampler(seed=args.seed).sample(
        args.shots, separate_observables=True
    )
    obs = np.asarray(obs, dtype=np.uint8)
    nobs = int(obs.shape[1])
    ordinary = Matching.from_detector_error_model(dem, enable_correlations=False)
    correlated = Matching.from_detector_error_model(dem, enable_correlations=True)
    ordinary_pred = as_obs(
        ordinary.decode_batch(dets, enable_correlations=False), args.shots, nobs
    )
    correlated_pred = as_obs(
        correlated.decode_batch(dets, enable_correlations=True), args.shots, nobs
    )
    ordinary_wrong = np.any(ordinary_pred != obs, axis=1)
    correlated_wrong = np.any(correlated_pred != obs, axis=1)
    n_ordinary = int(np.count_nonzero(ordinary_wrong))
    n_correlated = int(np.count_nonzero(correlated_wrong))
    o_rate, o_lo, o_hi = wilson(n_ordinary, args.shots)
    c_rate, c_lo, c_hi = wilson(n_correlated, args.shots)
    diff, d_lo, d_hi, n10, n01, n11 = paired_wald(correlated_wrong, ordinary_wrong)

    print(
        f"numpy={np.__version__}"
        f" pymatching={getattr(pymatching, '__version__', 'unknown')}"
        f" stim={getattr(stim, '__version__', 'unknown')}"
    )
    print(
        "circuit=surface_code:rotated_memory_z"
        f" distance={args.distance} rounds={args.rounds} p={args.p}"
        f" shots={args.shots} seed={args.seed}"
    )
    print(
        f"ordinary_logical_errors={n_ordinary}/{args.shots}"
        f" rate={fmt(o_rate)} wilson95=[{fmt(o_lo)}, {fmt(o_hi)}]"
    )
    print(
        f"correlated_logical_errors={n_correlated}/{args.shots}"
        f" rate={fmt(c_rate)} wilson95=[{fmt(c_lo)}, {fmt(c_hi)}]"
    )
    print(
        f"paired_diff_correlated_minus_ordinary={fmt(diff)}"
        f" wald95=[{fmt(d_lo)}, {fmt(d_hi)}]"
        f" n10_correlated_only={n10} n01_ordinary_only={n01} n11_both={n11}"
    )


if __name__ == "__main__":
    main()
