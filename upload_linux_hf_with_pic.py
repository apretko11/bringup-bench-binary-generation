#!/usr/bin/env python3

import argparse
import shlex
import subprocess
from pathlib import Path

from datasets import Dataset, DatasetDict


REPO = Path(__file__).resolve().parent

TARGETS = {
    "arm_linux": {
        "generated": REPO / "generated_arm64_reloc",
        "repo_id": "adpretko/bringup_arm_linux_reloc",
    },
    "riscv_linux": {
        "generated": REPO / "generated_riscv64_reloc",
        "repo_id": "adpretko/bringup_riscv_linux_reloc",
    },
    "x86_linux": {
        "generated": REPO / "generated_x86_reloc",
        "repo_id": "adpretko/bringup_x86_linux_reloc",
    },
}

SPLITS = ["O0", "O2"]

# Keep the six existing columns in exactly the same order, then append the two
# new PIC-family reference columns.
EXPECTED_COLUMNS = [
    "problem_name",
    "source_code",
    "compiler_asm",
    "object_asm",
    "shared_asm",
    "program_asm",
    "compiler_pic_asm",
    "pic_object_asm",
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
            f"{bench_dir.name}: unexpected LOCAL_OBJS entry: {object_name}"
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
        f"{bench_dir.name}: could not find source for {object_name}"
    )


def combine_files(paths):
    parts = []

    for path in sorted(paths, key=lambda p: str(p)):
        text = path.read_text(errors="replace").rstrip()

        if not text:
            raise RuntimeError(f"Empty file: {path}")

        parts.append(
            f"===== {path.name} =====\n"
            f"{text}\n"
        )

    return "\n".join(parts)


def read_text(path):
    if not path.exists():
        raise FileNotFoundError(path)

    text = path.read_text(errors="replace")
    if not text:
        raise RuntimeError(f"Empty file: {path}")

    return text


def build_row(benchmark, opt, generated_root):
    bench_dir = REPO / benchmark
    generated_dir = generated_root / opt / benchmark

    prog = make_var(bench_dir, "PROG") or benchmark

    local_objs = shlex.split(
        make_var(bench_dir, "LOCAL_OBJS")
    )

    if not local_objs:
        fallback = bench_dir / f"{prog}.c"
        if fallback.exists():
            local_objs = [f"{prog}.o"]
        else:
            raise RuntimeError(
                f"{benchmark}: unable to determine source files"
            )

    source_paths = [
        source_for_object(bench_dir, obj)
        for obj in local_objs
    ]

    asm_paths = sorted(
        (generated_dir / "asm").glob("*.s")
    )

    pic_asm_paths = sorted(
        (generated_dir / "pic_asm").glob("*.s")
    )

    if not asm_paths:
        raise RuntimeError(
            f"{benchmark} {opt}: no normal .s files found"
        )

    if not pic_asm_paths:
        raise RuntimeError(
            f"{benchmark} {opt}: no PIC .s files found"
        )

    if len(asm_paths) != len(local_objs):
        raise RuntimeError(
            f"{benchmark} {opt}: expected {len(local_objs)} normal .s files, "
            f"found {len(asm_paths)}"
        )

    if len(pic_asm_paths) != len(local_objs):
        raise RuntimeError(
            f"{benchmark} {opt}: expected {len(local_objs)} PIC .s files, "
            f"found {len(pic_asm_paths)}"
        )

    return {
        "problem_name": benchmark,
        "source_code": combine_files(source_paths),

        # Existing columns: untouched.
        "compiler_asm": combine_files(asm_paths),
        "object_asm": read_text(
            generated_dir / f"{prog}.o.objdump"
        ),
        "shared_asm": read_text(
            generated_dir / f"{prog}.so.objdump"
        ),
        "program_asm": read_text(
            generated_dir / f"{prog}.program.objdump"
        ),

        # New PIC family.
        "compiler_pic_asm": combine_files(pic_asm_paths),
        "pic_object_asm": read_text(
            generated_dir / f"{prog}.pic.o.objdump"
        ),
    }


def build_dataset_dict(generated_root, benchmarks):
    splits = {}

    for opt in SPLITS:
        rows = []

        for benchmark in benchmarks:
            print(f"  {opt}: {benchmark}")
            rows.append(
                build_row(
                    benchmark,
                    opt,
                    generated_root,
                )
            )

        splits[opt] = Dataset.from_list(rows)

    return DatasetDict(splits)


def validate_dataset(target_name, ds, benchmark_count):
    assert set(ds.keys()) == {"O0", "O2"}

    for opt in SPLITS:
        split = ds[opt]

        assert split.num_rows == benchmark_count
        assert split.column_names == EXPECTED_COLUMNS

        names = split["problem_name"]
        assert len(names) == len(set(names))

        for row in split:
            for column in EXPECTED_COLUMNS:
                if not row[column]:
                    raise RuntimeError(
                        f"{target_name} {opt} "
                        f"{row['problem_name']}: "
                        f"empty column {column}"
                    )

    assert ds["O0"]["problem_name"] == ds["O2"]["problem_name"]

    print()
    print(f"{target_name} VALIDATION PASS")
    print(f"  O0: {ds['O0'].num_rows} rows")
    print(f"  O2: {ds['O2'].num_rows} rows")
    print(f"  columns: {ds['O0'].column_names}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGETS),
        help=(
            "Target to build/upload. May be repeated. "
            "Default: all three Linux targets."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Build and validate locally but do not push to Hugging Face.",
    )
    args = parser.parse_args()

    selected_targets = args.target or list(TARGETS)

    benchmarks = shlex.split(
        make_var(REPO, "BMARKS")
    )

    if not benchmarks:
        raise RuntimeError("No benchmarks found in BMARKS")

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 BringupBench problems, found {len(benchmarks)}"
        )

    print(f"BringupBench problems: {len(benchmarks)}")

    datasets_to_upload = {}

    # Build and validate ALL selected datasets before uploading anything.
    for target_name in selected_targets:
        config = TARGETS[target_name]

        print()
        print("=" * 72)
        print(f"BUILDING {target_name}")
        print("=" * 72)

        ds = build_dataset_dict(
            config["generated"],
            benchmarks,
        )

        validate_dataset(
            target_name,
            ds,
            len(benchmarks),
        )

        datasets_to_upload[target_name] = ds

    print()
    print("=" * 72)
    print("ALL SELECTED LOCAL DATASETS VALIDATED")
    print("=" * 72)

    if args.validate_only:
        print("VALIDATE-ONLY requested: nothing uploaded.")
        return

    for target_name in selected_targets:
        config = TARGETS[target_name]
        ds = datasets_to_upload[target_name]
        repo_id = config["repo_id"]

        print()
        print("=" * 72)
        print(f"UPLOADING {target_name}")
        print(f"-> {repo_id}")
        print("=" * 72)

        ds.push_to_hub(repo_id)

        print(f"UPLOAD COMPLETE: {repo_id}")

    print()
    print("=" * 72)
    print("COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
