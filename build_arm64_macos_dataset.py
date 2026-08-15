#!/usr/bin/env python3

import re
import shlex
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent
COMMON = REPO / "common"
TARGET = REPO / "target"

OUT = REPO / "generated_arm64_mac"

CC = "clang"
AR = "ar"
OBJDUMP = ["xcrun", "llvm-objdump"]

OPT_LEVELS = {
    "O0": "-O0",
    "O2": "-O2",
}

BASE_FLAGS = [
    "-Wall",
    "-g",
    "-Wno-strict-aliasing",
    "-DTARGET_HOST",
    "-DTARGET_PERFHOOKS",
    "-Icommon",
    "-Itarget",
    "-arch",
    "arm64",
]


def run(cmd, cwd=REPO, stdout_path=None):
    cmd = [str(x) for x in cmd]
    print("+", shlex.join(cmd))

    if stdout_path is None:
        subprocess.run(cmd, cwd=cwd, check=True)
    else:
        stdout_path = Path(stdout_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        with stdout_path.open("w") as f:
            subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                stdout=f,
            )


def check_tools():
    for tool in [CC, AR, "make", "xcrun"]:
        if shutil.which(tool) is None:
            raise RuntimeError(f"Required tool not found: {tool}")

    subprocess.run(
        ["xcrun", "--find", "llvm-objdump"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def ensure_macos_libtarg_patch():
    """
    Bringup-Bench's clang branch defines ssize_t as:

        typedef signed __SIZE_TYPE__ ssize_t;

    Apple Clang defines __SIZE_TYPE__ as 'long unsigned int', making the
    expansion invalid. On macOS ARM64, __PTRDIFF_TYPE__ is the corresponding
    signed pointer-sized type.

    Apply the minimal patch automatically and idempotently.
    """

    path = TARGET / "libtarg.h"
    text = path.read_text()

    patched = "typedef __PTRDIFF_TYPE__ ssize_t;"

    if patched in text:
        print("Mac libtarg.h ssize_t patch already present.")
        return

    pattern = r"typedef\s+signed\s+__SIZE_TYPE__\s+ssize_t;"

    if not re.search(pattern, text):
        raise RuntimeError(
            "Could not find expected ssize_t definition in target/libtarg.h"
        )

    text = re.sub(
        pattern,
        patched,
        text,
        count=1,
    )

    path.write_text(text)

    print("Applied macOS ssize_t compatibility patch to target/libtarg.h.")


def make_var(directory, variable):
    """
    Ask the benchmark's own Makefile for a variable rather than attempting
    to reimplement the Bringup-Bench Makefile logic.
    """

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
    """
    Translate a Makefile object such as foo.o into its source foo.c.
    """

    obj = Path(object_name)

    if obj.suffix != ".o":
        raise RuntimeError(
            f"Unexpected LOCAL_OBJS entry in {bench_dir.name}: {object_name}"
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
        f"Could not find C source corresponding to {object_name} "
        f"for benchmark {bench_dir.name}"
    )


def safe_output_name(object_name):
    """
    Avoid directory components inside generated normal/pic directories.
    """

    return object_name.replace("/", "__")


def compile_support(opt_name, opt_flag):
    opt_root = OUT / opt_name
    support = opt_root / "_support"

    normal_dir = support / "normal"
    pic_dir = support / "pic"

    normal_libmin_dir = normal_dir / "libmin"
    pic_libmin_dir = pic_dir / "libmin"

    normal_libmin_dir.mkdir(parents=True, exist_ok=True)
    pic_libmin_dir.mkdir(parents=True, exist_ok=True)

    flags = BASE_FLAGS + [opt_flag]

    # libtarg normal
    normal_libtarg = normal_dir / "libtarg.o"

    run([
        CC,
        *flags,
        "-c",
        TARGET / "libtarg.c",
        "-o",
        normal_libtarg,
    ])

    # libtarg PIC
    pic_libtarg = pic_dir / "libtarg.o"

    run([
        CC,
        *flags,
        "-fPIC",
        "-c",
        TARGET / "libtarg.c",
        "-o",
        pic_libtarg,
    ])

    normal_libmin_objects = []
    pic_libmin_objects = []

    for src in sorted(COMMON.glob("libmin_*.c")):
        normal_obj = normal_libmin_dir / f"{src.stem}.o"
        pic_obj = pic_libmin_dir / f"{src.stem}.o"

        run([
            CC,
            *flags,
            "-c",
            src,
            "-o",
            normal_obj,
        ])

        run([
            CC,
            *flags,
            "-fPIC",
            "-c",
            src,
            "-o",
            pic_obj,
        ])

        normal_libmin_objects.append(normal_obj)
        pic_libmin_objects.append(pic_obj)

    normal_archive = normal_dir / "libmin.a"
    pic_archive = pic_dir / "libmin.a"

    # Remove old archives so rerunning the script cannot retain stale members.
    normal_archive.unlink(missing_ok=True)
    pic_archive.unlink(missing_ok=True)

    run([
        AR,
        "rcs",
        normal_archive,
        *normal_libmin_objects,
    ])

    run([
        AR,
        "rcs",
        pic_archive,
        *pic_libmin_objects,
    ])

    return {
        "normal_libtarg": normal_libtarg,
        "pic_libtarg": pic_libtarg,
        "normal_libmin": normal_archive,
        "pic_libmin": pic_archive,
    }


def build_benchmark(name, opt_name, opt_flag, support):
    bench_dir = REPO / name

    print()
    print("=" * 72)
    print(f"{name} {opt_name}")
    print("=" * 72)

    prog = make_var(bench_dir, "PROG")

    if not prog:
        prog = name

    local_objs_text = make_var(bench_dir, "LOCAL_OBJS")
    local_cflags_text = make_var(bench_dir, "LOCAL_CFLAGS")

    local_objs = shlex.split(local_objs_text)
    local_cflags = shlex.split(local_cflags_text)

    # Most Bringup benchmarks specify LOCAL_OBJS. Fall back to PROG.o if
    # necessary.
    if not local_objs:
        candidate = bench_dir / f"{prog}.c"

        if candidate.exists():
            local_objs = [f"{prog}.o"]
        else:
            raise RuntimeError(
                f"{name}: LOCAL_OBJS is empty and {prog}.c does not exist"
            )

    flags = BASE_FLAGS + local_cflags + [opt_flag]

    # Same compatibility fix required by the Linux generators.
    if name == "highlife":
        flags.append("-fgnu89-inline")

    bench_out = OUT / opt_name / name

    asm_dir = bench_out / "asm"
    normal_dir = bench_out / "normal"
    pic_dir = bench_out / "pic"

    asm_dir.mkdir(parents=True, exist_ok=True)
    normal_dir.mkdir(parents=True, exist_ok=True)
    pic_dir.mkdir(parents=True, exist_ok=True)

    normal_objects = []
    pic_objects = []

    for object_name in local_objs:
        source = source_for_object(bench_dir, object_name)

        output_name = safe_output_name(object_name)

        normal_obj = normal_dir / output_name
        pic_obj = pic_dir / output_name

        asm_name = Path(output_name).with_suffix(".s").name
        asm_file = asm_dir / asm_name

        # Compiler-generated assembly.
        run([
            CC,
            *flags,
            "-S",
            source,
            "-o",
            asm_file,
        ])

        # Normal relocatable object.
        run([
            CC,
            *flags,
            "-c",
            source,
            "-o",
            normal_obj,
        ])

        # PIC object for dylib.
        run([
            CC,
            *flags,
            "-fPIC",
            "-c",
            source,
            "-o",
            pic_obj,
        ])

        normal_objects.append(normal_obj)
        pic_objects.append(pic_obj)

    # Produce one final relocatable object per benchmark.
    final_object = bench_out / f"{prog}.o"

    if len(normal_objects) == 1:
        shutil.copy2(normal_objects[0], final_object)
    else:
        run([
            CC,
            "-arch",
            "arm64",
            "-r",
            "-o",
            final_object,
            *normal_objects,
        ])

    # Native Mach-O executable.
    program = bench_out / f"{prog}.program"

    run([
        CC,
        "-arch",
        "arm64",
        "-o",
        program,
        *normal_objects,
        support["normal_libtarg"],
        support["normal_libmin"],
    ])

    # Mach-O dynamic library.
    dylib = bench_out / f"{prog}.dylib"

    run([
        CC,
        "-arch",
        "arm64",
        "-dynamiclib",
        "-o",
        dylib,
        *pic_objects,
        support["pic_libtarg"],
        support["pic_libmin"],
    ])

    # Full disassemblies.
    run(
        [
            *OBJDUMP,
            "-d",
            final_object,
        ],
        stdout_path=bench_out / f"{prog}.o.objdump",
    )

    run(
        [
            *OBJDUMP,
            "-d",
            dylib,
        ],
        stdout_path=bench_out / f"{prog}.dylib.objdump",
    )

    run(
        [
            *OBJDUMP,
            "-d",
            program,
        ],
        stdout_path=bench_out / f"{prog}.program.objdump",
    )


def main():
    check_tools()
    ensure_macos_libtarg_patch()

    benchmarks_text = make_var(REPO, "BMARKS")
    benchmarks = shlex.split(benchmarks_text)

    if not benchmarks:
        raise RuntimeError("No benchmarks found in BMARKS")

    print(f"Repository: {REPO}")
    print(f"Output:     {OUT}")
    print(f"Benchmarks: {len(benchmarks)}")

    failures = []

    for opt_name, opt_flag in OPT_LEVELS.items():
        print()
        print("#" * 72)
        print(f"BUILDING {opt_name}")
        print("#" * 72)

        support = compile_support(opt_name, opt_flag)

        for name in benchmarks:
            try:
                build_benchmark(
                    name,
                    opt_name,
                    opt_flag,
                    support,
                )
            except Exception as exc:
                print()
                print(f"FAILED: {name} {opt_name}")
                print(exc)

                failures.append(
                    (name, opt_name, str(exc))
                )

    print()
    print("=" * 72)
    print("COMPLETE")
    print("=" * 72)

    if failures:
        print(f"{len(failures)} build(s) failed:")

        for name, opt_name, error in failures:
            print(f"  {name} {opt_name}: {error}")

        raise SystemExit(1)

    print("All benchmarks succeeded.")


if __name__ == "__main__":
    main()
