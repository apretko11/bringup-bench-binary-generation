#!/usr/bin/env python3

"""
Enrich the EXISTING live Bringup-Bench ARM64 macOS relocation-preserving
dataset on Hugging Face with:

    compiler_pic_asm
    pic_object_asm

Target repo:
    adpretko/bringup_arm_mac_reloc

Local tree:
    generated_arm64_mac_reloc/{O0,O2}/...

Safety:
- Loads the CURRENT live HF dataset first.
- Preserves its row order and all six existing columns.
- Reconstructs each existing six-column row from the local reloc tree and
  requires exact text equality before adding anything.
- Adds only compiler_pic_asm and pic_object_asm.
- --validate-only performs all checks without uploading.
- After upload, force-reloads the live dataset and verifies it.
"""

import argparse
import shlex
import subprocess
from pathlib import Path

from datasets import Dataset, DatasetDict, load_dataset

REPO = Path(__file__).resolve().parent
GENERATED = REPO / "generated_arm64_mac_reloc"
TARGET_REPO = "adpretko/bringup_arm_mac_reloc"

SPLITS = ("O0", "O2")
EXPECTED_ROWS = 108

OLD_COLUMNS = [
    "problem_name",
    "source_code",
    "compiler_asm",
    "object_asm",
    "shared_asm",
    "program_asm",
]

FINAL_COLUMNS = OLD_COLUMNS + [
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
    Match the existing Bringup uploader's deterministic concatenation format.
    """
    parts = []

    for path in sorted(paths, key=lambda p: str(p)):
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).rstrip()

        if not text:
            raise RuntimeError(f"Empty file: {path}")

        parts.append(
            f"===== {path.name} =====\n"
            f"{text}\n"
        )

    return "\n".join(parts)


def read_text(path):
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(path)

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    if not text:
        raise RuntimeError(f"Empty file: {path}")

    return text


def benchmark_names():
    names = shlex.split(make_var(REPO, "BMARKS"))

    if len(names) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS} benchmarks from BMARKS, "
            f"found {len(names)}"
        )

    if len(set(names)) != EXPECTED_ROWS:
        raise RuntimeError("Duplicate benchmark names in BMARKS")

    return names


def build_local_row(benchmark, opt):
    bench_dir = REPO / benchmark
    generated_dir = GENERATED / opt / benchmark

    if not generated_dir.is_dir():
        raise RuntimeError(
            f"Missing generated directory: {generated_dir}"
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

    # Match the original uploader exactly for compiler_asm.
    asm_paths = sorted(
        (generated_dir / "asm").glob("*.s")
    )

    if not asm_paths:
        raise RuntimeError(
            f"{benchmark} {opt}: "
            f"no compiler assembly files found"
        )

    # PIC compiler assembly was generated one-for-one from LOCAL_OBJS.
    pic_asm_paths = [
        generated_dir
        / "pic_asm"
        / Path(obj).with_suffix(".s")
        for obj in local_objs
    ]

    for path in pic_asm_paths:
        if not path.is_file():
            raise RuntimeError(
                f"{benchmark} {opt}: "
                f"missing PIC compiler assembly {path}"
            )

    pic_object_dump = (
        generated_dir
        / f"{prog}.pic.o.objdump"
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

        "compiler_pic_asm": combine_files(
            pic_asm_paths
        ),

        "pic_object_asm": read_text(
            pic_object_dump
        ),
    }


def build_local_index(opt):
    out = {}

    for benchmark in benchmark_names():
        row = build_local_row(
            benchmark,
            opt,
        )

        if benchmark in out:
            raise RuntimeError(
                f"{opt}: duplicate benchmark {benchmark}"
            )

        out[benchmark] = row

    return out


def enrich_split(opt, live_split):
    if live_split.num_rows != EXPECTED_ROWS:
        raise RuntimeError(
            f"{opt}: live HF has {live_split.num_rows} rows; "
            f"expected {EXPECTED_ROWS}"
        )

    if live_split.column_names != OLD_COLUMNS:
        raise RuntimeError(
            f"{opt}: unexpected live HF columns\n"
            f"Expected: {OLD_COLUMNS}\n"
            f"Actual:   {live_split.column_names}"
        )

    local = build_local_index(opt)

    live_names = list(
        live_split["problem_name"]
    )

    if len(set(live_names)) != EXPECTED_ROWS:
        raise RuntimeError(
            f"{opt}: duplicate problem_name values in live HF"
        )

    if set(live_names) != set(local):
        missing_local = sorted(
            set(live_names) - set(local)
        )
        extra_local = sorted(
            set(local) - set(live_names)
        )

        raise RuntimeError(
            f"{opt}: live/local benchmark-name mismatch\n"
            f"Missing locally: {missing_local}\n"
            f"Extra locally:   {extra_local}"
        )

    cols = {
        name: []
        for name in FINAL_COLUMNS
    }

    for i, live_row in enumerate(live_split):
        benchmark = live_row["problem_name"]
        local_row = local[benchmark]

        # Prove we are enriching the exact current live dataset.
        for col in OLD_COLUMNS:
            if live_row[col] != local_row[col]:
                raise RuntimeError(
                    f"{opt} row {i} ({benchmark}): "
                    f"live HF {col!r} does not match local reconstruction"
                )

        for col in OLD_COLUMNS:
            cols[col].append(
                live_row[col]
            )

        cols["compiler_pic_asm"].append(
            local_row["compiler_pic_asm"]
        )

        cols["pic_object_asm"].append(
            local_row["pic_object_asm"]
        )

    ds = Dataset.from_dict(cols)

    if ds.num_rows != EXPECTED_ROWS:
        raise RuntimeError(
            f"{opt}: final row count mismatch"
        )

    if ds.column_names != FINAL_COLUMNS:
        raise RuntimeError(
            f"{opt}: final column order mismatch\n"
            f"Expected: {FINAL_COLUMNS}\n"
            f"Actual:   {ds.column_names}"
        )

    if any(
        not x.strip()
        for x in ds["compiler_pic_asm"]
    ):
        raise RuntimeError(
            f"{opt}: empty compiler_pic_asm value"
        )

    if any(
        not x.strip()
        for x in ds["pic_object_asm"]
    ):
        raise RuntimeError(
            f"{opt}: empty pic_object_asm value"
        )

    return ds


def verify_live():
    print()
    print("=" * 78)
    print("RELOADING LIVE HUGGING FACE DATASET")
    print("=" * 78)

    live = load_dataset(
        TARGET_REPO,
        download_mode="force_redownload",
    )

    if set(live.keys()) != set(SPLITS):
        raise RuntimeError(
            f"Unexpected live splits: {list(live.keys())}"
        )

    for opt in SPLITS:
        ds = live[opt]

        print(f"{opt}: {ds.num_rows} rows")
        print(f"{opt}: {ds.column_names}")

        if ds.num_rows != EXPECTED_ROWS:
            raise RuntimeError(
                f"{opt}: live row count mismatch"
            )

        if ds.column_names != FINAL_COLUMNS:
            raise RuntimeError(
                f"{opt}: live column mismatch"
            )

        if any(
            not x.strip()
            for x in ds["compiler_pic_asm"]
        ):
            raise RuntimeError(
                f"{opt}: empty live compiler_pic_asm value"
            )

        if any(
            not x.strip()
            for x in ds["pic_object_asm"]
        ):
            raise RuntimeError(
                f"{opt}: empty live pic_object_asm value"
            )

    if (
        live["O0"]["problem_name"]
        != live["O2"]["problem_name"]
    ):
        raise RuntimeError(
            "Live O0/O2 problem ordering differs"
        )

    if (
        live["O0"]["source_code"]
        != live["O2"]["source_code"]
    ):
        raise RuntimeError(
            "Live O0/O2 source_code differs"
        )

    print("O0/O2 problem ordering: PASS")
    print("O0/O2 source_code identity: PASS")
    print("LIVE HF VERIFICATION: PASS")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate/package locally but do not upload.",
    )

    parser.add_argument(
        "--verify-live",
        action="store_true",
        help="Only reload and verify the current live HF dataset.",
    )

    args = parser.parse_args()

    if args.verify_live:
        verify_live()
        return

    if not GENERATED.is_dir():
        raise SystemExit(
            f"Missing generated dataset root:\n{GENERATED}"
        )

    print("=" * 78)
    print("LOADING CURRENT LIVE BRINGUP ARM64 MACOS DATASET")
    print("=" * 78)
    print(TARGET_REPO)

    live = load_dataset(
        TARGET_REPO
    )

    if set(live.keys()) != set(SPLITS):
        raise RuntimeError(
            f"Unexpected live splits: {list(live.keys())}"
        )

    enriched = {}

    for opt in SPLITS:
        print()
        print("=" * 78)
        print(f"VALIDATING + ENRICHING {opt}")
        print("=" * 78)

        enriched[opt] = enrich_split(
            opt,
            live[opt],
        )

        print(
            f"{opt}: rows = "
            f"{enriched[opt].num_rows}"
        )
        print(
            f"{opt}: columns = "
            f"{enriched[opt].column_names}"
        )
        print(f"{opt}: PASS")

    dataset = DatasetDict(
        enriched
    )

    if (
        dataset["O0"]["problem_name"]
        != dataset["O2"]["problem_name"]
    ):
        raise RuntimeError(
            "O0/O2 problem ordering differs"
        )

    if (
        dataset["O0"]["source_code"]
        != dataset["O2"]["source_code"]
    ):
        raise RuntimeError(
            "O0/O2 source_code differs"
        )

    print()
    print("=" * 78)
    print("LOCAL PACKAGING SUMMARY")
    print("=" * 78)

    for opt in SPLITS:
        print(
            f"{opt}: {dataset[opt].num_rows} rows, "
            f"{len(dataset[opt].column_names)} columns"
        )

    print("O0/O2 problem ordering: PASS")
    print("O0/O2 source_code identity: PASS")
    print("LOCAL VALIDATION: PASS")
    print("Final columns:", FINAL_COLUMNS)

    if args.validate_only:
        print(
            "No upload performed (--validate-only)."
        )
        return

    print()
    print("=" * 78)
    print("UPLOADING TO HUGGING FACE")
    print("=" * 78)
    print(TARGET_REPO)

    dataset.push_to_hub(
        TARGET_REPO
    )

    print("UPLOAD COMPLETE")

    verify_live()


if __name__ == "__main__":
    main()
