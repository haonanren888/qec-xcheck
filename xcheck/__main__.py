"""python -m xcheck <check> [options] [input]

Checks:
  known                         known-defect regression table and JSON
  stim-cirq-roundtrip           a Stim circuit file
  cirq-classical-control        a Cirq JSON file, or builtin:8525
  qasm3-roundtrip               an OpenQASM 3 file
  distance                      DEM-fault counterexample check (own exit codes)

cirq-classical-control accepts --oracle. Each of the nested, unrolled,
and JSON simulations is then compared with the independent reference,
not only with the other paths.

Exit status for known, stim-cirq-roundtrip, cirq-classical-control, and
qasm3-roundtrip is 0 when the invariants hold, 1 when they do not, and 2
on a usage or runtime error. `known` exits 1 when any executed check is FAIL.

`distance` exits 0 for EXHAUSTIVE_NONE, 1 for COUNTEREXAMPLE, 2 on a
usage error or DECODER_OUTPUT_INVALID, 3 for SAMPLED_NONE, and 4 for
UNAVAILABLE. A counterexample already found stays exit 1 when a later
weight is not enumerated.
"""

from __future__ import annotations

import json
import sys

from xcheck.env import ensure_cache_env

_CHECKS = (
    "stim-cirq-roundtrip",
    "cirq-classical-control",
    "qasm3-roundtrip",
)


def _usage() -> None:
    print(
        "usage: python -m xcheck known\n"
        "       python -m xcheck cirq-classical-control [--oracle] <json-or-builtin:8525>\n"
        "       python -m xcheck <stim-cirq-roundtrip|qasm3-roundtrip> <input>\n"
        "       python -m xcheck distance --circuit <stim file> "
        "[--decoder pymatching|pymatching-correlated|tesseract|toy-broken|custom:module:function] "
        "[--max-weight 1|2] [--sample-pairs N] [--max-pairs N] [--json]",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    ensure_cache_env()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "distance":
        from xcheck.distance import main as distance_main

        return distance_main(args[1:])
    if args == ["known"]:
        from xcheck.known.suite import run_known

        payload = run_known()
        print(payload["table"])
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(payload["exit_code"])
    use_oracle = False
    if "--oracle" in args:
        use_oracle = True
        args = [item for item in args if item != "--oracle"]
    if len(args) != 2 or args[0] not in _CHECKS:
        _usage()
        return 2
    if use_oracle and args[0] != "cirq-classical-control":
        _usage()
        return 2
    name, path = args
    try:
        if name == "stim-cirq-roundtrip":
            from xcheck.stim_cirq import check_file

            result = check_file(path)
        elif name == "cirq-classical-control":
            from xcheck.cirq_control import check_circuit, check_file

            if path == "builtin:8525":
                from xcheck.known.circuits import circuit_8525

                result = check_circuit(circuit_8525(), path, use_oracle=use_oracle)
            else:
                result = check_file(path, use_oracle=use_oracle)
        else:
            from xcheck.qasm3_rt import check_file

            result = check_file(path)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "pass":
        return 0
    if result["status"] == "mismatch":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
