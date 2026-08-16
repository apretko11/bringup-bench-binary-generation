#!/usr/bin/env python3

import shlex
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent

TARGETS = {
    "arm_linux": {
        "old": REPO / "generated_arm64",
        "new": REPO / "generated_arm64_reloc",
        "objdump": "aarch64-linux-gnu-objdump",
        "format": "elf64-littleaarch64",
    },
    "riscv_linux": {
        "old": REPO / "generated_riscv64",
        "new": REPO / "generated_riscv64_reloc",
        "objdump": "riscv64-linux-gnu-objdump",
        "format": "elf64-littleriscv",
    },
    "x86_linux": {
        "old": REPO / "generated_x86",
        "new": REPO / "generated_x86_reloc",
        "objdump": "objdump",
        "format": "elf64-x86-64",
    },
}

SPLITS = ["O0", "O2"]


def make_var(directory, variable):
    helper_text = (
        "include Makefile\n\n"
        "print-var:\n"
        f'\t@printf \'%s\\n\' "$({variable})"\n'
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".mk",
        dir=directory,
        delete=False,
    ) as f:
        f.write(helper_text)
        helper = Path(f.name)

    try:
        result = subprocess.run(
            [
                "make", "-s",
                "-f", helper.name,
                "TARGET=host",
                "print-var",
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        helper.unlink()

    return result.stdout.strip()


def require_file(path):
    if not path.is_file():
        raise RuntimeError(f"MISSING: {path}")

    if path.stat().st_size == 0:
        raise RuntimeError(f"EMPTY: {path}")


def normalize_objdump_header(text):
    """
    Remove the filename/file-format header line so paths such as
    generated_arm64 vs generated_arm64_reloc do not count as
    disassembly differences.
    """

    return "\n".join(
        line
        for line in text.splitlines()
        if "file format" not in line
    )


def fresh_objdump(objdump, flags, binary):
    result = subprocess.run(
        [objdump, flags, str(binary)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def compare_disassembly(objdump, old, new):
    """
    Compare executable instruction disassembly rather than raw binary
    bytes. Raw binaries can differ because -g embeds build paths in
    DWARF/debug metadata.
    """

    require_file(old)
    require_file(new)

    old_text = fresh_objdump(objdump, "-d", old)
    new_text = fresh_objdump(objdump, "-d", new)

    old_text = normalize_objdump_header(old_text)
    new_text = normalize_objdump_header(new_text)

    if old_text != new_text:
        raise RuntimeError(
            f"UNEXPECTED DISASSEMBLY DIFFERENCE:\n"
            f"  old: {old}\n"
            f"  new: {new}"
        )


def main():
    benchmarks = shlex.split(make_var(REPO, "BMARKS"))

    print(f"Expected Bringup benchmarks: {len(benchmarks)}")

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, found {len(benchmarks)}"
        )

    grand_total = 0

    for target_name, config in TARGETS.items():
        print()
        print("=" * 72)
        print(target_name)
        print("=" * 72)

        for opt in SPLITS:
            checked = 0
            dumps_changed = {
                "object": 0,
                "shared": 0,
                "program": 0,
            }

            for benchmark in benchmarks:
                bench_dir = REPO / benchmark
                prog = make_var(bench_dir, "PROG") or benchmark

                old = config["old"] / opt / benchmark
                new = config["new"] / opt / benchmark

                if not old.is_dir():
                    raise RuntimeError(f"MISSING OLD DIR: {old}")

                if not new.is_dir():
                    raise RuntimeError(f"MISSING NEW DIR: {new}")

                # -------------------------------------------------
                # 1. Compiler-generated .s file sets must match.
                #    Contents may differ in debug paths because -g
                #    records the directory used during compilation.
                # -------------------------------------------------
                old_asm = old / "asm"
                new_asm = new / "asm"

                old_s = sorted(p.name for p in old_asm.glob("*.s"))
                new_s = sorted(p.name for p in new_asm.glob("*.s"))

                if not old_s:
                    raise RuntimeError(f"No old .s files: {old_asm}")

                if old_s != new_s:
                    raise RuntimeError(
                        f".s FILE SET DIFFERENCE: {target_name} "
                        f"{opt} {benchmark}"
                    )

                for name in old_s:
                    require_file(old_asm / name)
                    require_file(new_asm / name)

                # -------------------------------------------------
                # 2. Executable instruction disassembly of the
                #    underlying binaries must be unchanged.
                # -------------------------------------------------
                binaries = [
                    f"{prog}.o",
                    f"{prog}.so",
                    f"{prog}.program",
                ]

                for name in binaries:
                    compare_disassembly(
                        config["objdump"],
                        old / name,
                        new / name,
                    )

                # -------------------------------------------------
                # 3. Required new dump files must exist.
                # -------------------------------------------------
                obj = new / f"{prog}.o"
                so = new / f"{prog}.so"
                program = new / f"{prog}.program"

                obj_dump = new / f"{prog}.o.objdump"
                so_dump = new / f"{prog}.so.objdump"
                program_dump = new / f"{prog}.program.objdump"

                for path in [obj_dump, so_dump, program_dump]:
                    require_file(path)

                # -------------------------------------------------
                # 4. Saved dumps must EXACTLY equal the intended
                #    fresh objdump commands.
                # -------------------------------------------------
                expected_obj = fresh_objdump(
                    config["objdump"], "-dr", obj
                )
                expected_so = fresh_objdump(
                    config["objdump"], "-drR", so
                )
                expected_program = fresh_objdump(
                    config["objdump"], "-drR", program
                )

                actual_obj = obj_dump.read_text(errors="replace")
                actual_so = so_dump.read_text(errors="replace")
                actual_program = program_dump.read_text(errors="replace")

                if actual_obj != expected_obj:
                    raise RuntimeError(
                        f"OBJECT DUMP MISMATCH: "
                        f"{target_name} {opt} {benchmark}"
                    )

                if actual_so != expected_so:
                    raise RuntimeError(
                        f"SHARED DUMP MISMATCH: "
                        f"{target_name} {opt} {benchmark}"
                    )

                if actual_program != expected_program:
                    raise RuntimeError(
                        f"PROGRAM DUMP MISMATCH: "
                        f"{target_name} {opt} {benchmark}"
                    )

                # -------------------------------------------------
                # 5. Correct ISA / binary format.
                # -------------------------------------------------
                fmt = config["format"]

                for label, text in [
                    ("object", actual_obj),
                    ("shared", actual_so),
                    ("program", actual_program),
                ]:
                    if fmt not in text:
                        raise RuntimeError(
                            f"WRONG FORMAT: {target_name} {opt} "
                            f"{benchmark} {label}; expected {fmt}"
                        )

                # -------------------------------------------------
                # 6. Count how many dumps changed versus the old -d
                #    representation. Ignore only the filename/header
                #    line because the output directory changed.
                # -------------------------------------------------
                old_obj_dump = old / f"{prog}.o.objdump"
                old_so_dump = old / f"{prog}.so.objdump"
                old_program_dump = old / f"{prog}.program.objdump"

                require_file(old_obj_dump)
                require_file(old_so_dump)
                require_file(old_program_dump)

                old_obj_text = normalize_objdump_header(
                    old_obj_dump.read_text(errors="replace")
                )
                old_so_text = normalize_objdump_header(
                    old_so_dump.read_text(errors="replace")
                )
                old_program_text = normalize_objdump_header(
                    old_program_dump.read_text(errors="replace")
                )

                new_obj_text = normalize_objdump_header(actual_obj)
                new_so_text = normalize_objdump_header(actual_so)
                new_program_text = normalize_objdump_header(
                    actual_program
                )

                if old_obj_text != new_obj_text:
                    dumps_changed["object"] += 1

                if old_so_text != new_so_text:
                    dumps_changed["shared"] += 1

                if old_program_text != new_program_text:
                    dumps_changed["program"] += 1

                checked += 1
                grand_total += 1

            print(
                f"{opt}: PASS — {checked}/108 benchmarks\n"
                f"    object dumps changed:  "
                f"{dumps_changed['object']}/108\n"
                f"    shared dumps changed:  "
                f"{dumps_changed['shared']}/108\n"
                f"    program dumps changed: "
                f"{dumps_changed['program']}/108"
            )

    print()
    print("=" * 72)
    print("ALL SIX LINUX DATASETS PASS")
    print(f"Validated benchmark/target/split instances: {grand_total}")
    print("=" * 72)


if __name__ == "__main__":
    main()
