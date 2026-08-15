#!/usr/bin/env python3

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
OUT = REPO / "generated_arm64"

CC = "aarch64-linux-gnu-gcc"
AR = "aarch64-linux-gnu-ar"
OBJDUMP = "aarch64-linux-gnu-objdump"

BASE_FLAGS = [
    "-Wall",
    "-g",
    "-Wno-strict-aliasing",
    "-DTARGET_HOST",
    "-DTARGET_PERFHOOKS",
    f"-I{REPO / 'common'}",
    f"-I{REPO / 'target'}",
]


def run(cmd, cwd=None, stdout_file=None):
    print("+", " ".join(map(str, cmd)))

    if stdout_file:
        with open(stdout_file, "w") as f:
            subprocess.run(
                list(map(str, cmd)),
                cwd=cwd,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
    else:
        subprocess.run(
            list(map(str, cmd)),
            cwd=cwd,
            check=True,
        )


def get_make_vars(directory, names):
    """Ask the benchmark's actual Makefiles for variable values."""

    helper_text = "include Makefile\n\nprint-gen-vars:\n"
    for name in names:
        helper_text += f'\t@printf \'{name}=%s\\n\' "$({name})"\n'

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
                "make",
                "-s",
                "-f",
                helper.name,
                "TARGET=host",
                "print-gen-vars",
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


def build_support(opt):
    """Build normal and PIC ARM64 versions of libmin/libtarg."""

    opt_root = OUT / opt
    normal = opt_root / "_support" / "normal"
    pic = opt_root / "_support" / "pic"

    normal.mkdir(parents=True, exist_ok=True)
    pic.mkdir(parents=True, exist_ok=True)

    flags = BASE_FLAGS + [f"-{opt}"]

    # libtarg
    run([
        CC, *flags,
        "-c", REPO / "target/libtarg.c",
        "-o", normal / "libtarg.o"
    ])

    run([
        CC, *flags, "-fPIC",
        "-c", REPO / "target/libtarg.c",
        "-o", pic / "libtarg.o"
    ])

    normal_libmin = []
    pic_libmin = []

    for src in sorted((REPO / "common").glob("libmin_*.c")):
        normal_obj = normal / f"{src.stem}.o"
        pic_obj = pic / f"{src.stem}.o"

        run([
            CC, *flags,
            "-c", src,
            "-o", normal_obj
        ])

        run([
            CC, *flags, "-fPIC",
            "-c", src,
            "-o", pic_obj
        ])

        normal_libmin.append(normal_obj)
        pic_libmin.append(pic_obj)

    run([AR, "rcs", normal / "libmin.a", *normal_libmin])
    run([AR, "rcs", pic / "libmin.a", *pic_libmin])

    return normal, pic


def build_benchmark(name, opt, normal_support, pic_support):
    bench = REPO / name

    variables = get_make_vars(
        bench,
        ["PROG", "LOCAL_OBJS", "LOCAL_CFLAGS"]
    )

    prog = variables["PROG"]
    local_objs = shlex.split(variables["LOCAL_OBJS"])
    local_flags = shlex.split(variables.get("LOCAL_CFLAGS", ""))

    out = OUT / opt / name
    normal_dir = out / "normal"
    pic_dir = out / "pic"
    asm_dir = out / "asm"

    normal_dir.mkdir(parents=True, exist_ok=True)
    pic_dir.mkdir(parents=True, exist_ok=True)
    asm_dir.mkdir(parents=True, exist_ok=True)

    flags = BASE_FLAGS + [f"-{opt}"] + local_flags

    # Required for highlife at O0 because of its inline functions.
    if name == "highlife":
        flags.append("-fgnu89-inline")

    normal_objects = []
    pic_objects = []

    for obj_name in local_objs:

        if not obj_name.endswith(".o"):
            raise RuntimeError(f"Unexpected LOCAL_OBJS entry: {obj_name}")

        src_name = obj_name[:-2] + ".c"
        src = bench / src_name

        if not src.exists():
            raise RuntimeError(f"Source not found for {obj_name}: {src}")

        safe_name = obj_name.replace("/", "__")

        normal_obj = normal_dir / safe_name
        pic_obj = pic_dir / safe_name
        asm_file = asm_dir / (safe_name[:-2] + ".s")

        # Compiler-generated ARM64 assembly
        run([
            CC, *flags,
            "-I", bench,
            "-S", src,
            "-o", asm_file
        ])

        # Normal ARM64 relocatable object
        run([
            CC, *flags,
            "-I", bench,
            "-c", src,
            "-o", normal_obj
        ])

        # PIC object for ARM64 .so
        run([
            CC, *flags, "-fPIC",
            "-I", bench,
            "-c", src,
            "-o", pic_obj
        ])

        normal_objects.append(normal_obj)
        pic_objects.append(pic_obj)

    # One relocatable .o representing the benchmark.
    final_obj = out / f"{prog}.o"

    if len(normal_objects) == 1:
        shutil.copy2(normal_objects[0], final_obj)
    else:
        run([
            CC, "-r",
            "-o", final_obj,
            *normal_objects
        ])

    # ARM64 Linux executable
    program = out / f"{prog}.program"

    run([
        CC,
        "-o", program,
        *normal_objects,
        normal_support / "libtarg.o",
        normal_support / "libmin.a",
        normal_support / "libmin.a",
    ])

    # ARM64 Linux shared library
    shared = out / f"{prog}.so"

    run([
        CC,
        "-shared",
        "-o", shared,
        *pic_objects,
        pic_support / "libtarg.o",
        pic_support / "libmin.a",
        pic_support / "libmin.a",
    ])

    # Binary-recovered assembly
    run(
        [OBJDUMP, "-d", final_obj],
        stdout_file=out / f"{prog}.o.objdump"
    )

    run(
        [OBJDUMP, "-d", shared],
        stdout_file=out / f"{prog}.so.objdump"
    )

    run(
        [OBJDUMP, "-d", program],
        stdout_file=out / f"{prog}.program.objdump"
    )


def main():

    for tool in [CC, AR, OBJDUMP, "make"]:
        if shutil.which(tool) is None:
            raise SystemExit(f"Missing required tool: {tool}")

    root_vars = get_make_vars(REPO, ["BMARKS"])
    benchmarks = root_vars["BMARKS"].split()

    print(f"Found {len(benchmarks)} Bringup benchmarks")

    failures = []

    for opt in ["O0", "O2"]:

        print(f"\n===== {opt} SUPPORT =====")
        normal_support, pic_support = build_support(opt)

        for i, benchmark in enumerate(benchmarks, 1):
            print(
                f"\n===== {opt}: "
                f"{benchmark} ({i}/{len(benchmarks)}) ====="
            )

            try:
                build_benchmark(
                    benchmark,
                    opt,
                    normal_support,
                    pic_support
                )

            except Exception as e:
                print(f"FAILED: {benchmark}: {e}")
                failures.append((opt, benchmark, str(e)))

    print("\n===== COMPLETE =====")

    if failures:
        print(f"{len(failures)} failures:")
        for opt, benchmark, error in failures:
            print(f"  {opt} {benchmark}: {error}")
    else:
        print("All benchmarks succeeded.")


if __name__ == "__main__":
    main()
