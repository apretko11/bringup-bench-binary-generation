#!/usr/bin/env python3

import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent
OUT = REPO / "generated_arm64_mac_reloc"

OBJDUMP = ["xcrun", "llvm-objdump"]
SPLITS = ["O0", "O2"]


def make_var(directory, variable):
    makefile = f"""
include Makefile

.PHONY: __print_var
__print_var:
\t@printf '%s\\n' "$({variable})"
"""

    result = subprocess.run(
        [
            "make",
            "-s",
            "-f",
            "-",
            "TARGET=host",
            "__print_var",
        ],
        cwd=directory,
        input=makefile,
        text=True,
        capture_output=True,
        check=True,
    )

    return result.stdout.strip()


def run_objdump(flags, binary, output):
    print(
        "+",
        *OBJDUMP,
        flags,
        binary,
        ">",
        output,
    )

    with output.open("w") as f:
        subprocess.run(
            [
                *OBJDUMP,
                flags,
                str(binary),
            ],
            stdout=f,
            check=True,
            text=True,
        )


def main():
    benchmarks = shlex.split(
        make_var(REPO, "BMARKS")
    )

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, found {len(benchmarks)}"
        )

    if not OUT.is_dir():
        raise RuntimeError(
            f"Missing copied output directory: {OUT}"
        )

    total = 0

    for split in SPLITS:
        print()
        print("=" * 72)
        print(split)
        print("=" * 72)

        for benchmark in benchmarks:
            bench_dir = REPO / benchmark

            prog = make_var(
                bench_dir,
                "PROG",
            )

            if not prog:
                prog = benchmark

            out = OUT / split / benchmark

            obj = out / f"{prog}.o"
            dylib = out / f"{prog}.dylib"
            program = out / f"{prog}.program"

            for path in [obj, dylib, program]:
                if not path.is_file():
                    raise RuntimeError(
                        f"Missing binary: {path}"
                    )

            run_objdump(
                "-dr",
                obj,
                out / f"{prog}.o.objdump",
            )

            run_objdump(
                "-drR",
                dylib,
                out / f"{prog}.dylib.objdump",
            )

            run_objdump(
                "-drR",
                program,
                out / f"{prog}.program.objdump",
            )

            total += 1

    print()
    print("=" * 72)
    print("RELOCATION-PRESERVING OBJDUMPS COMPLETE")
    print(f"Benchmark/split instances processed: {total}")
    print("=" * 72)


if __name__ == "__main__":
    main()
