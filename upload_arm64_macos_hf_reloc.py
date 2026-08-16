#!/usr/bin/env python3

import shlex
import subprocess
from pathlib import Path

from datasets import Dataset, DatasetDict


REPO = Path(__file__).resolve().parent

GENERATED = REPO / "generated_arm64_mac_reloc"
REPO_ID = "adpretko/bringup_arm_mac_reloc"

SPLITS = ["O0", "O2"]

EXPECTED_COLUMNS = [
    "problem_name",
    "source_code",
    "compiler_asm",
    "object_asm",
    "shared_asm",
    "program_asm",
]


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
            f"Unexpected LOCAL_OBJS entry for "
            f"{bench_dir.name}: {object_name}"
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
        f"Could not find source for "
        f"{object_name} in {bench_dir.name}"
    )


def combine_files(paths):
    """
    Concatenate multiple C or .s files deterministically while
    preserving their filenames.
    """

    parts = []

    for path in sorted(paths, key=lambda p: str(p)):
        text = path.read_text(
            errors="replace"
        ).rstrip()

        parts.append(
            f"===== {path.name} =====\n"
            f"{text}\n"
        )

    return "\n".join(parts)


def read_text(path):
    if not path.exists():
        raise FileNotFoundError(path)

    text = path.read_text(
        errors="replace"
    )

    if not text:
        raise RuntimeError(
            f"Empty file: {path}"
        )

    return text


def build_row(benchmark, opt):
    bench_dir = REPO / benchmark
    generated_dir = (
        GENERATED
        / opt
        / benchmark
    )

    prog = make_var(
        bench_dir,
        "PROG",
    )

    if not prog:
        prog = benchmark

    local_objs_text = make_var(
        bench_dir,
        "LOCAL_OBJS",
    )

    local_objs = shlex.split(
        local_objs_text
    )

    if not local_objs:
        candidate = (
            bench_dir
            / f"{prog}.c"
        )

        if candidate.exists():
            local_objs = [
                f"{prog}.o"
            ]
        else:
            raise RuntimeError(
                f"{benchmark}: "
                f"cannot determine benchmark source files"
            )

    source_paths = [
        source_for_object(
            bench_dir,
            obj,
        )
        for obj in local_objs
    ]

    asm_paths = sorted(
        (generated_dir / "asm").glob("*.s")
    )

    if not asm_paths:
        raise RuntimeError(
            f"{benchmark} {opt}: "
            f"no compiler assembly files found"
        )

    return {
        "problem_name": benchmark,

        "source_code": combine_files(
            source_paths
        ),

        "compiler_asm": combine_files(
            asm_paths
        ),

        "object_asm": read_text(
            generated_dir
            / f"{prog}.o.objdump"
        ),

        "shared_asm": read_text(
            generated_dir
            / f"{prog}.dylib.objdump"
        ),

        "program_asm": read_text(
            generated_dir
            / f"{prog}.program.objdump"
        ),
    }


def build_dataset(benchmarks):
    splits = {}

    for opt in SPLITS:
        rows = []

        for benchmark in benchmarks:
            print(
                f"{opt}: {benchmark}"
            )

            rows.append(
                build_row(
                    benchmark,
                    opt,
                )
            )

        splits[opt] = Dataset.from_list(
            rows
        )

    return DatasetDict(
        splits
    )


def validate_dataset(ds, benchmark_count):
    if set(ds.keys()) != {"O0", "O2"}:
        raise RuntimeError(
            f"Unexpected splits: {list(ds.keys())}"
        )

    for opt in SPLITS:
        split = ds[opt]

        if split.num_rows != benchmark_count:
            raise RuntimeError(
                f"{opt}: expected "
                f"{benchmark_count} rows, "
                f"found {split.num_rows}"
            )

        if split.column_names != EXPECTED_COLUMNS:
            raise RuntimeError(
                f"{opt}: wrong columns\n"
                f"expected: {EXPECTED_COLUMNS}\n"
                f"actual:   {split.column_names}"
            )

        names = split["problem_name"]

        if len(names) != len(set(names)):
            raise RuntimeError(
                f"{opt}: duplicate problem names"
            )

        for row in split:
            for column in EXPECTED_COLUMNS:
                if not row[column]:
                    raise RuntimeError(
                        f"{opt} "
                        f"{row['problem_name']}: "
                        f"empty column {column}"
                    )

        print()
        print(
            f"{opt}: PASS — "
            f"{split.num_rows} rows"
        )

    if (
        ds["O0"]["problem_name"]
        != ds["O2"]["problem_name"]
    ):
        raise RuntimeError(
            "O0/O2 problem ordering mismatch"
        )

    if (
        ds["O0"]["source_code"]
        != ds["O2"]["source_code"]
    ):
        raise RuntimeError(
            "O0/O2 source_code mismatch"
        )

    print("O0/O2 problem ordering: PASS")
    print("O0/O2 source_code identity: PASS")

    for column in [
        "compiler_asm",
        "object_asm",
        "shared_asm",
        "program_asm",
    ]:
        identical = []

        for i in range(benchmark_count):
            if (
                ds["O0"][i][column]
                == ds["O2"][i][column]
            ):
                identical.append(
                    ds["O0"][i]["problem_name"]
                )

        print(
            f"{column}: "
            f"{benchmark_count - len(identical)} differ, "
            f"{len(identical)} identical"
        )

        if identical:
            print(
                "  identical:",
                ", ".join(identical),
            )


def main():
    benchmarks_text = make_var(
        REPO,
        "BMARKS",
    )

    benchmarks = shlex.split(
        benchmarks_text
    )

    if not benchmarks:
        raise RuntimeError(
            "No benchmarks found in BMARKS"
        )

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, "
            f"found {len(benchmarks)}"
        )

    print(
        f"BringupBench problems: "
        f"{len(benchmarks)}"
    )

    print()
    print("=" * 72)
    print("BUILDING DATASET")
    print("=" * 72)

    ds = build_dataset(
        benchmarks
    )

    print()
    print("=" * 72)
    print("VALIDATING LOCAL DATASET")
    print("=" * 72)

    validate_dataset(
        ds,
        len(benchmarks),
    )

    print()
    print(ds)

    print()
    print("=" * 72)
    print("LOCAL DATASET VALIDATED")
    print("=" * 72)

    print()
    print("=" * 72)
    print("UPLOADING")
    print(f"-> {REPO_ID}")
    print("=" * 72)

    ds.push_to_hub(
        REPO_ID
    )

    print()
    print(
        f"UPLOAD COMPLETE: "
        f"{REPO_ID}"
    )


if __name__ == "__main__":
    main()
