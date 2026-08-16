#!/usr/bin/env python3

import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent

OLD = REPO / "generated_arm64_mac"
NEW = REPO / "generated_arm64_mac_reloc"

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


def require_file(path):
    if not path.is_file():
        raise RuntimeError(f"MISSING: {path}")

    if path.stat().st_size == 0:
        raise RuntimeError(f"EMPTY: {path}")


def compare_exact(old, new):
    require_file(old)
    require_file(new)

    if old.read_bytes() != new.read_bytes():
        raise RuntimeError(
            "UNEXPECTED BYTE DIFFERENCE:\n"
            f"  old: {old}\n"
            f"  new: {new}"
        )


def fresh_objdump(flags, binary):
    result = subprocess.run(
        [
            *OBJDUMP,
            flags,
            str(binary),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout


def normalize_objdump_path(text):
    """
    Normalize only the old/new generated-root names so that the
    informational changed-count is not triggered merely because
    llvm-objdump prints the input filename.
    """

    text = text.replace(
        str(NEW),
        "<GENERATED_ROOT>",
    )

    text = text.replace(
        str(OLD),
        "<GENERATED_ROOT>",
    )

    text = text.replace(
        NEW.name,
        "<GENERATED_ROOT>",
    )

    text = text.replace(
        OLD.name,
        "<GENERATED_ROOT>",
    )

    return text


def main():
    benchmarks = shlex.split(
        make_var(REPO, "BMARKS")
    )

    print(f"Expected Bringup benchmarks: {len(benchmarks)}")

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, found {len(benchmarks)}"
        )

    if not OLD.is_dir():
        raise RuntimeError(
            f"Missing old generated directory: {OLD}"
        )

    if not NEW.is_dir():
        raise RuntimeError(
            f"Missing new generated directory: {NEW}"
        )

    grand_total = 0

    print()
    print("=" * 72)
    print("arm64_macos")
    print("=" * 72)

    for split in SPLITS:
        checked = 0

        dumps_changed = {
            "object": 0,
            "dylib": 0,
            "program": 0,
        }

        for benchmark in benchmarks:
            bench_dir = REPO / benchmark

            prog = make_var(
                bench_dir,
                "PROG",
            )

            if not prog:
                prog = benchmark

            old = OLD / split / benchmark
            new = NEW / split / benchmark

            if not old.is_dir():
                raise RuntimeError(
                    f"MISSING OLD DIR: {old}"
                )

            if not new.is_dir():
                raise RuntimeError(
                    f"MISSING NEW DIR: {new}"
                )

            # -------------------------------------------------
            # 1. Old/new benchmark file sets must be identical.
            # -------------------------------------------------
            old_files = {
                p.relative_to(old)
                for p in old.rglob("*")
                if p.is_file()
            }

            new_files = {
                p.relative_to(new)
                for p in new.rglob("*")
                if p.is_file()
            }

            if old_files != new_files:
                missing = sorted(
                    str(p)
                    for p in old_files - new_files
                )

                extra = sorted(
                    str(p)
                    for p in new_files - old_files
                )

                raise RuntimeError(
                    f"FILE SET DIFFERENCE: "
                    f"{split} {benchmark}\n"
                    f"missing: {missing}\n"
                    f"extra: {extra}"
                )

            # -------------------------------------------------
            # 2. EVERY non-objdump artifact must remain
            #    byte-for-byte identical.
            #
            #    This includes:
            #      compiler .s
            #      normal .o files
            #      PIC .o files
            #      final .o
            #      .dylib
            #      .program
            #
            #    Only *.objdump is allowed to change.
            # -------------------------------------------------
            for relative in sorted(
                old_files,
                key=str,
            ):
                if relative.name.endswith(".objdump"):
                    continue

                compare_exact(
                    old / relative,
                    new / relative,
                )

            # -------------------------------------------------
            # 3. Identify final binary/dump artifacts.
            # -------------------------------------------------
            obj = new / f"{prog}.o"
            dylib = new / f"{prog}.dylib"
            program = new / f"{prog}.program"

            obj_dump = new / f"{prog}.o.objdump"
            dylib_dump = new / f"{prog}.dylib.objdump"
            program_dump = new / f"{prog}.program.objdump"

            for path in [
                obj,
                dylib,
                program,
                obj_dump,
                dylib_dump,
                program_dump,
            ]:
                require_file(path)

            # -------------------------------------------------
            # 4. New dumps must EXACTLY equal fresh executions
            #    of the intended commands.
            # -------------------------------------------------
            expected_obj = fresh_objdump(
                "-dr",
                obj,
            )

            expected_dylib = fresh_objdump(
                "-drR",
                dylib,
            )

            expected_program = fresh_objdump(
                "-drR",
                program,
            )

            actual_obj = obj_dump.read_text(
                errors="replace"
            )

            actual_dylib = dylib_dump.read_text(
                errors="replace"
            )

            actual_program = program_dump.read_text(
                errors="replace"
            )

            if actual_obj != expected_obj:
                raise RuntimeError(
                    f"OBJECT DUMP MISMATCH: "
                    f"{split} {benchmark}"
                )

            if actual_dylib != expected_dylib:
                raise RuntimeError(
                    f"DYLIB DUMP MISMATCH: "
                    f"{split} {benchmark}"
                )

            if actual_program != expected_program:
                raise RuntimeError(
                    f"PROGRAM DUMP MISMATCH: "
                    f"{split} {benchmark}"
                )

            # -------------------------------------------------
            # 5. Correct Mach-O ARM64 format.
            # -------------------------------------------------
            for label, text in [
                ("object", actual_obj),
                ("dylib", actual_dylib),
                ("program", actual_program),
            ]:
                if "mach-o arm64" not in text:
                    raise RuntimeError(
                        f"WRONG FORMAT: "
                        f"{split} {benchmark} {label}; "
                        f"expected Mach-O arm64"
                    )

            # -------------------------------------------------
            # 6. Informational: count which dataset objdump
            #    strings changed compared with the original -d
            #    versions.
            #
            #    Ignore only the input-path difference.
            # -------------------------------------------------
            old_obj_dump = (
                old / f"{prog}.o.objdump"
            )

            old_dylib_dump = (
                old / f"{prog}.dylib.objdump"
            )

            old_program_dump = (
                old / f"{prog}.program.objdump"
            )

            require_file(old_obj_dump)
            require_file(old_dylib_dump)
            require_file(old_program_dump)

            old_obj_text = normalize_objdump_path(
                old_obj_dump.read_text(
                    errors="replace"
                )
            )

            old_dylib_text = normalize_objdump_path(
                old_dylib_dump.read_text(
                    errors="replace"
                )
            )

            old_program_text = normalize_objdump_path(
                old_program_dump.read_text(
                    errors="replace"
                )
            )

            new_obj_text = normalize_objdump_path(
                actual_obj
            )

            new_dylib_text = normalize_objdump_path(
                actual_dylib
            )

            new_program_text = normalize_objdump_path(
                actual_program
            )

            if old_obj_text != new_obj_text:
                dumps_changed["object"] += 1

            if old_dylib_text != new_dylib_text:
                dumps_changed["dylib"] += 1

            if old_program_text != new_program_text:
                dumps_changed["program"] += 1

            checked += 1
            grand_total += 1

        print(
            f"{split}: PASS — {checked}/108 benchmarks\n"
            f"    object dumps changed:  "
            f"{dumps_changed['object']}/108\n"
            f"    dylib dumps changed:   "
            f"{dumps_changed['dylib']}/108\n"
            f"    program dumps changed: "
            f"{dumps_changed['program']}/108"
        )

    print()
    print("=" * 72)
    print("BOTH BRINGUP MACOS DATASETS PASS")
    print(
        f"Validated benchmark/split instances: "
        f"{grand_total}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
