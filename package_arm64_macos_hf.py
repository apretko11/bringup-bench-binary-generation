#!/usr/bin/env python3

import json
import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent
GENERATED = REPO / "generated_arm64_mac"
OUTPUT = REPO / "hf_arm64_mac"

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


def source_for_object(bench_dir, object_name):
    obj = Path(object_name)

    if obj.suffix != ".o":
        raise RuntimeError(
            f"Unexpected LOCAL_OBJS entry for {bench_dir.name}: {object_name}"
        )

    source_rel = obj.with_suffix(".c")

    candidates = [
        bench_dir / source_rel,
        REPO / source_rel,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not find source for {object_name} in {bench_dir.name}"
    )


def combine_files(paths):
    """
    Concatenate one or more files deterministically, preserving filenames.
    """

    parts = []

    for path in sorted(paths, key=lambda p: str(p)):
        parts.append(
            f"===== {path.name} =====\n"
            f"{path.read_text(errors='replace').rstrip()}\n"
        )

    return "\n".join(parts)


def read_text(path):
    if not path.exists():
        raise FileNotFoundError(path)

    return path.read_text(errors="replace")


def build_row(benchmark, opt):
    bench_dir = REPO / benchmark
    generated_dir = GENERATED / opt / benchmark

    prog = make_var(bench_dir, "PROG")
    if not prog:
        prog = benchmark

    local_objs_text = make_var(bench_dir, "LOCAL_OBJS")
    local_objs = shlex.split(local_objs_text)

    if not local_objs:
        candidate = bench_dir / f"{prog}.c"

        if candidate.exists():
            local_objs = [f"{prog}.o"]
        else:
            raise RuntimeError(
                f"{benchmark}: cannot determine benchmark source files"
            )

    # All benchmark-local C sources contributing to the final benchmark.
    source_paths = [
        source_for_object(bench_dir, obj)
        for obj in local_objs
    ]

    # All compiler-generated assembly files for the benchmark.
    asm_paths = sorted(
        (generated_dir / "asm").glob("*.s")
    )

    if not asm_paths:
        raise RuntimeError(
            f"{benchmark} {opt}: no compiler assembly files found"
        )

    object_path = generated_dir / f"{prog}.o.objdump"
    shared_path = generated_dir / f"{prog}.dylib.objdump"
    program_path = generated_dir / f"{prog}.program.objdump"

    return {
        "problem_name": benchmark,
        "source_code": combine_files(source_paths),
        "compiler_asm": combine_files(asm_paths),
        "object_asm": read_text(object_path),
        "shared_asm": read_text(shared_path),
        "program_asm": read_text(program_path),
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    benchmarks_text = make_var(REPO, "BMARKS")
    benchmarks = shlex.split(benchmarks_text)

    if not benchmarks:
        raise RuntimeError("No benchmarks found in BMARKS")

    print(f"Benchmarks: {len(benchmarks)}")

    for opt in SPLITS:
        output_path = OUTPUT / f"{opt}.jsonl"

        rows = []

        for benchmark in benchmarks:
            print(f"{opt}: {benchmark}")
            rows.append(build_row(benchmark, opt))

        with output_path.open("w", encoding="utf-8") as f:
            for row in rows:
                json.dump(row, f, ensure_ascii=False)
                f.write("\n")

        print()
        print(f"Wrote {len(rows)} rows -> {output_path}")
        print()

    print("COMPLETE")


if __name__ == "__main__":
    main()
