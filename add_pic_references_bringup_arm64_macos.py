#!/usr/bin/env python3

"""
Add PIC-reference artifacts to the EXISTING Bringup-Bench ARM64 macOS
relocation-preserving dataset.

For each benchmark and optimization level this creates:

    pic_asm/.../*.s          compiler assembly generated with -fPIC -S
    <prog>.pic.o             combined relocatable PIC object
    <prog>.pic.o.objdump     relocation-preserving dump of that object

Important:
- Operates on generated_arm64_mac_reloc
- Reuses the EXISTING per-source PIC objects in each benchmark's pic/ directory
- Does NOT rebuild the existing PIC objects, dylib, normal object, or program
- Combines PIC objects with the same clang -arch arm64 -r strategy used for
  the normal relocatable object
- Uses xcrun llvm-objdump -dr for the combined PIC relocatable object
"""

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path

import build_arm64_macos_dataset_reloc as build

REPO = Path(__file__).resolve().parent
GENERATED = REPO / "generated_arm64_mac_reloc"

SPLITS = {
    "O0": "-O0",
    "O2": "-O2",
}

EXPECTED_BENCHMARKS = 108

OBJDUMP = ["xcrun", "llvm-objdump"]


def run(cmd, *, stdout_path=None):
    cmd = [str(x) for x in cmd]
    print("+", " ".join(cmd))

    if stdout_path is None:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
        )
    else:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("w", encoding="utf-8") as f:
            result = subprocess.run(
                cmd,
                text=True,
                stdout=f,
                stderr=subprocess.PIPE,
            )

    if result.returncode != 0:
        stdout = getattr(result, "stdout", "") or ""
        stderr = result.stderr or ""
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + stdout
            + "\n\nSTDERR:\n"
            + stderr
        )


def require_nonempty(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Missing file: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"Empty file: {path}")


def get_benchmarks():
    text = build.make_var(REPO, "BMARKS")
    benchmarks = shlex.split(text)

    if len(benchmarks) != EXPECTED_BENCHMARKS:
        raise RuntimeError(
            f"Expected {EXPECTED_BENCHMARKS} benchmarks from BMARKS, "
            f"found {len(benchmarks)}"
        )

    if len(set(benchmarks)) != len(benchmarks):
        raise RuntimeError("Duplicate benchmark names in BMARKS")

    return benchmarks


def benchmark_config(name: str, opt_flag: str):
    bench_dir = REPO / name

    prog = build.make_var(bench_dir, "PROG")
    if not prog:
        prog = name

    local_objs_text = build.make_var(bench_dir, "LOCAL_OBJS")
    local_cflags_text = build.make_var(bench_dir, "LOCAL_CFLAGS")

    local_objs = shlex.split(local_objs_text)
    local_cflags = shlex.split(local_cflags_text)

    if not local_objs:
        candidate = bench_dir / f"{prog}.c"
        if candidate.exists():
            local_objs = [f"{prog}.o"]
        else:
            raise RuntimeError(
                f"{name}: LOCAL_OBJS empty and {candidate} does not exist"
            )

    flags = list(build.BASE_FLAGS) + local_cflags + [opt_flag]

    if name == "highlife":
        flags.append("-fgnu89-inline")

    return bench_dir, prog, local_objs, flags


def build_one(name: str, split: str, opt_flag: str):
    bench_dir, prog, local_objs, flags = benchmark_config(
        name,
        opt_flag,
    )

    bench_out = GENERATED / split / name
    pic_dir = bench_out / "pic"
    pic_asm_dir = bench_out / "pic_asm"

    if not bench_out.is_dir():
        raise RuntimeError(f"Missing generated benchmark dir: {bench_out}")

    if not pic_dir.is_dir():
        raise RuntimeError(f"Missing existing PIC object dir: {pic_dir}")

    # Validate existing top-level artifacts before adding anything.
    for path in [
        bench_out / f"{prog}.o",
        bench_out / f"{prog}.o.objdump",
        bench_out / f"{prog}.dylib",
        bench_out / f"{prog}.dylib.objdump",
        bench_out / f"{prog}.program",
        bench_out / f"{prog}.program.objdump",
    ]:
        require_nonempty(path)

    pic_objects = []

    for object_name in local_objs:
        obj_rel = Path(object_name)

        if obj_rel.suffix != ".o":
            raise RuntimeError(
                f"{name}: unexpected LOCAL_OBJS entry {object_name!r}"
            )

        source = build.source_for_object(
            bench_dir,
            object_name,
        )

        require_nonempty(source)

        existing_pic_obj = pic_dir / obj_rel
        require_nonempty(existing_pic_obj)
        pic_objects.append(existing_pic_obj)

        # Preserve any relative subdirectory in LOCAL_OBJS.
        asm_rel = obj_rel.with_suffix(".s")
        compiler_pic_s = pic_asm_dir / asm_rel
        compiler_pic_s.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Same flags as the original per-source PIC object, but -S instead of -c.
        run([
            build.CC,
            *flags,
            "-fPIC",
            "-S",
            source,
            "-o",
            compiler_pic_s,
        ])

        require_nonempty(compiler_pic_s)

    # Produce a benchmark-level PIC relocatable object parallel to the
    # existing normal <prog>.o. The source PIC objects are NOT rebuilt.
    final_pic_object = bench_out / f"{prog}.pic.o"

    if len(pic_objects) == 1:
        shutil.copy2(
            pic_objects[0],
            final_pic_object,
        )
        print(
            f"+ copy {pic_objects[0]} -> {final_pic_object}"
        )
    else:
        run([
            build.CC,
            "-arch",
            "arm64",
            "-r",
            "-o",
            final_pic_object,
            *pic_objects,
        ])

    require_nonempty(final_pic_object)

    final_pic_dump = bench_out / f"{prog}.pic.o.objdump"

    run(
        [
            *OBJDUMP,
            "-dr",
            final_pic_object,
        ],
        stdout_path=final_pic_dump,
    )

    require_nonempty(final_pic_dump)

    return final_pic_dump, len(local_objs)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--split",
        action="append",
        choices=tuple(SPLITS),
        help="Repeatable. Default: O0 and O2.",
    )

    args = parser.parse_args()

    selected_splits = args.split or list(SPLITS)

    if not GENERATED.is_dir():
        raise SystemExit(
            f"Missing generated dataset root:\n{GENERATED}"
        )

    # Ensure the imported builder is the expected one.
    for attr in [
        "BASE_FLAGS",
        "CC",
        "make_var",
        "source_for_object",
    ]:
        if not hasattr(build, attr):
            raise SystemExit(
                f"Builder module missing expected attribute: {attr}"
            )

    benchmarks = get_benchmarks()

    completed = 0
    failures = []
    split_stats = {}

    for split in selected_splits:
        opt_flag = SPLITS[split]

        print()
        print("=" * 78)
        print(f"BRINGUP ARM64 MACOS PIC REFERENCES: {split}")
        print("=" * 78)

        rows_with_reloc = 0
        total_reloc_lines = 0
        total_source_objects = 0
        multi_source_benchmarks = 0

        for i, name in enumerate(benchmarks, 1):
            print(
                f"\n===== {split}: {name} "
                f"({i}/{EXPECTED_BENCHMARKS}) ====="
            )

            try:
                pic_dump, n_objects = build_one(
                    name,
                    split,
                    opt_flag,
                )

                completed += 1
                total_source_objects += n_objects

                if n_objects > 1:
                    multi_source_benchmarks += 1

                reloc_lines = [
                    line
                    for line in pic_dump.read_text(
                        errors="replace"
                    ).splitlines()
                    if "ARM64_RELOC_" in line
                ]

                if reloc_lines:
                    rows_with_reloc += 1
                    total_reloc_lines += len(reloc_lines)

            except Exception as exc:
                print(f"FAILED: {exc}")
                failures.append(
                    (split, name, str(exc))
                )

        split_stats[split] = {
            "rows_with_reloc": rows_with_reloc,
            "reloc_lines": total_reloc_lines,
            "source_objects": total_source_objects,
            "multi_source": multi_source_benchmarks,
        }

    expected = (
        len(selected_splits)
        * EXPECTED_BENCHMARKS
    )

    print()
    print("=" * 78)
    print("BRINGUP ARM64 MACOS PIC REFERENCE GENERATION SUMMARY")
    print("=" * 78)
    print(f"Expected benchmarks:  {expected}")
    print(f"Completed benchmarks: {completed}")
    print(f"Failures:             {len(failures)}")

    for split in selected_splits:
        stats = split_stats[split]
        print(
            f"{split}: {stats['source_objects']} source PIC objects; "
            f"{stats['multi_source']} multi-source benchmarks; "
            f"{stats['rows_with_reloc']}/{EXPECTED_BENCHMARKS} "
            f"combined PIC objects with ARM64 relocations; "
            f"{stats['reloc_lines']} ARM64_RELOC_ lines"
        )

    if failures:
        print()
        print("FAILURES:")
        for split, name, error in failures:
            print(f"  {split} {name}: {error}")
        raise SystemExit(1)

    if completed != expected:
        raise SystemExit(
            f"Expected {expected} completed benchmarks, "
            f"got {completed}"
        )

    print("OVERALL: PASS")


if __name__ == "__main__":
    main()
