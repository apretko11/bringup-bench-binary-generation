#!/usr/bin/env python3
"""
Add missing PIC-reference artifacts to the EXISTING Bringup-Bench Linux
relocatable outputs without rebuilding the existing normal object, executable,
or shared library.

Creates, for every benchmark/split:
  pic_asm/*.s
  <prog>.pic.o
  <prog>.pic.o.objdump
"""

import argparse
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent

BASE_FLAGS = [
    "-Wall",
    "-g",
    "-Wno-strict-aliasing",
    "-DTARGET_HOST",
    "-DTARGET_PERFHOOKS",
    f"-I{REPO / 'common'}",
    f"-I{REPO / 'target'}",
]

TARGETS = {
    "x86_linux": {
        "generated": REPO / "generated_x86_reloc",
        "cc": "gcc",
        "objdump": "objdump",
        "format": "elf64-x86-64",
    },
    "arm_linux": {
        "generated": REPO / "generated_arm64_reloc",
        "cc": "aarch64-linux-gnu-gcc",
        "objdump": "aarch64-linux-gnu-objdump",
        "format": "elf64-littleaarch64",
    },
    "riscv_linux": {
        "generated": REPO / "generated_riscv64_reloc",
        "cc": "riscv64-linux-gnu-gcc",
        "objdump": "riscv64-linux-gnu-objdump",
        "format": "elf64-littleriscv",
    },
}

SPLITS = ["O0", "O2"]


def run(cmd, cwd=None, stdout_file=None):
    cmd = list(map(str, cmd))
    print("+", " ".join(cmd))
    if stdout_file is not None:
        with open(stdout_file, "w") as f:
            subprocess.run(
                cmd,
                cwd=cwd,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
    else:
        subprocess.run(cmd, cwd=cwd, check=True)


def get_make_vars(directory, names):
    helper_text = "include Makefile\n\nprint-pic-vars:\n"
    for name in names:
        helper_text += f'\t@printf \'{name}=%s\\n\' "$({name})"\n'

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mk", dir=directory, delete=False
    ) as f:
        f.write(helper_text)
        helper = Path(f.name)

    try:
        result = subprocess.run(
            [
                "make", "-s", "-f", helper.name,
                "TARGET=host", "print-pic-vars",
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        helper.unlink()

    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()
    return values


def require_nonempty(path):
    if not path.is_file():
        raise RuntimeError(f"MISSING: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"EMPTY: {path}")


def build_one(target_name, config, opt, benchmark):
    bench = REPO / benchmark
    out = config["generated"] / opt / benchmark
    pic_dir = out / "pic"
    pic_asm_dir = out / "pic_asm"

    if not out.is_dir():
        raise RuntimeError(f"Missing generated directory: {out}")
    if not pic_dir.is_dir():
        raise RuntimeError(f"Missing existing PIC object directory: {pic_dir}")

    variables = get_make_vars(
        bench, ["PROG", "LOCAL_OBJS", "LOCAL_CFLAGS"]
    )
    prog = variables["PROG"] or benchmark
    local_objs = shlex.split(variables["LOCAL_OBJS"])
    local_flags = shlex.split(variables.get("LOCAL_CFLAGS", ""))

    if not local_objs:
        raise RuntimeError(f"{benchmark}: LOCAL_OBJS is empty")

    flags = BASE_FLAGS + [f"-{opt}"] + local_flags
    if benchmark == "highlife":
        flags.append("-fgnu89-inline")

    pic_asm_dir.mkdir(parents=True, exist_ok=True)
    pic_objects = []

    for obj_name in local_objs:
        if not obj_name.endswith(".o"):
            raise RuntimeError(
                f"{benchmark}: unexpected LOCAL_OBJS entry: {obj_name}"
            )

        src = bench / (obj_name[:-2] + ".c")
        if not src.exists():
            raise RuntimeError(
                f"{benchmark}: source not found for {obj_name}: {src}"
            )

        safe_name = obj_name.replace("/", "__")
        pic_obj = pic_dir / safe_name
        require_nonempty(pic_obj)
        pic_objects.append(pic_obj)

        pic_asm_file = pic_asm_dir / (safe_name[:-2] + ".s")
        run([
            config["cc"], *flags, "-fPIC",
            "-I", bench,
            "-S", src,
            "-o", pic_asm_file,
        ])
        require_nonempty(pic_asm_file)

    final_pic_obj = out / f"{prog}.pic.o"
    if len(pic_objects) == 1:
        shutil.copy2(pic_objects[0], final_pic_obj)
    else:
        run([
            config["cc"], "-r",
            "-o", final_pic_obj,
            *pic_objects,
        ])
    require_nonempty(final_pic_obj)

    pic_objdump = out / f"{prog}.pic.o.objdump"
    run(
        [config["objdump"], "-dr", final_pic_obj],
        stdout_file=pic_objdump,
    )
    require_nonempty(pic_objdump)

    if config["format"] not in pic_objdump.read_text(errors="replace"):
        raise RuntimeError(
            f"{target_name} {opt} {benchmark}: wrong PIC object format; "
            f"expected {config['format']}"
        )

    return len(pic_objects)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGETS),
        help="Repeatable. Default: all three Linux targets.",
    )
    parser.add_argument(
        "--split",
        action="append",
        choices=SPLITS,
        help="Repeatable. Default: O0 and O2.",
    )
    args = parser.parse_args()

    targets = args.target or list(TARGETS)
    splits = args.split or SPLITS

    for target_name in targets:
        config = TARGETS[target_name]
        for tool in [config["cc"], config["objdump"], "make"]:
            if shutil.which(tool) is None:
                raise SystemExit(
                    f"{target_name}: missing required tool: {tool}"
                )
        if not config["generated"].is_dir():
            raise SystemExit(
                f"{target_name}: missing generated root: "
                f"{config['generated']}"
            )

    benchmarks = get_make_vars(REPO, ["BMARKS"])["BMARKS"].split()
    if len(benchmarks) != 108:
        raise SystemExit(
            f"Expected 108 Bringup benchmarks, found {len(benchmarks)}"
        )

    failures = []
    completed = 0
    source_objects = 0

    for target_name in targets:
        config = TARGETS[target_name]
        for opt in splits:
            print()
            print("=" * 78)
            print(f"{target_name} {opt}")
            print("=" * 78)

            for i, benchmark in enumerate(benchmarks, 1):
                print(
                    f"\n===== {target_name} {opt}: "
                    f"{benchmark} ({i}/{len(benchmarks)}) ====="
                )
                try:
                    source_objects += build_one(
                        target_name, config, opt, benchmark
                    )
                    completed += 1
                except Exception as exc:
                    print(f"FAILED: {exc}")
                    failures.append(
                        (target_name, opt, benchmark, str(exc))
                    )

    expected = len(targets) * len(splits) * len(benchmarks)

    print()
    print("=" * 78)
    print("PIC REFERENCE GENERATION SUMMARY")
    print("=" * 78)
    print(f"Expected instances:  {expected}")
    print(f"Completed instances: {completed}")
    print(f"PIC source objects:   {source_objects}")
    print(f"Failures:             {len(failures)}")

    if failures:
        for target_name, opt, benchmark, error in failures:
            print(f"  {target_name} {opt} {benchmark}: {error}")
        raise SystemExit(1)

    if completed != expected:
        raise SystemExit(
            f"Expected {expected} completed instances, got {completed}"
        )

    print("OVERALL: PASS")


if __name__ == "__main__":
    main()
