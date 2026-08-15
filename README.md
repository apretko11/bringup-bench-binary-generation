# Bringup-Bench Binary Dataset Generation

Scripts used to generate multiple binary/assembly representations of the [Bringup-Bench](https://github.com/toddmaustin/bringup-bench) benchmark suite for cross-ISA translation experiments.

## Upstream source

Bringup-Bench repository:

`https://github.com/toddmaustin/bringup-bench`

Exact upstream commit used:

```text
604470a1d23d37f94be08a750813b3b3d6049c8c
```

Accessed: **August 15, 2026**

To reproduce the source tree exactly:

```bash
git clone https://github.com/toddmaustin/bringup-bench.git
cd bringup-bench
git checkout 604470a1d23d37f94be08a750813b3b3d6049c8c
```

The original Bringup-Bench source is **not duplicated in this repository**.

## Generated targets

The Linux generation scripts currently cover:

* x86-64 Linux
* AArch64 Linux
* RISC-V 64 Linux

ARM64 macOS generation is performed separately on an Apple Silicon Mac and will use a corresponding macOS generation script.

For every benchmark, artifacts are generated at both:

* `O0`
* `O2`

## Generated representations

For each benchmark and optimization level, four representations are produced.

### 1. Compiler-generated assembly

C source is compiled directly to `.s`:

```text
C → compiler → .s
```

### 2. Relocatable object

C source is compiled to an ELF relocatable object:

```text
C → compiler/assembler → .o
```

The `.o` is then disassembled with the target-specific `objdump`.

### 3. Shared object

Position-independent code is compiled with `-fPIC` and linked with the required Bringup-Bench support code:

```text
C + libmin + libtarg
        ↓
      .so
```

The resulting `.so` is then disassembled.

### 4. Executable

The benchmark is linked with the actual Bringup-Bench support library:

```text
benchmark objects
+ libmin
+ libtarg
    ↓
Linux PIE executable
```

The complete executable is then disassembled.

No attempt is made to filter the resulting executable disassembly to only benchmark functions. The goal is to preserve the assembly that would be observed when disassembling an actual linked binary.

## Bringup-Bench support code

Bringup-Bench supplies its own `libmin` library and target interface.

The generation scripts use the support code directly from the pinned upstream repository rather than replacing it with custom implementations.

Benchmark-specific source files, headers, and Makefile settings are also retained.

The scripts query the Bringup-Bench Makefiles for:

```text
BMARKS
PROG
LOCAL_OBJS
LOCAL_CFLAGS
```

This allows benchmarks containing multiple source files or benchmark-specific headers to be compiled using their actual repository structure.

## Scripts

### x86-64 Linux

```bash
python build_x86_dataset.py
```

Output:

```text
generated_x86/
├── O0/
└── O2/
```

### AArch64 Linux

Requires an AArch64 Linux cross-toolchain:

```bash
sudo apt install \
    gcc-aarch64-linux-gnu \
    binutils-aarch64-linux-gnu \
    libc6-dev-arm64-cross \
    qemu-user
```

Run:

```bash
python build_arm64_dataset.py
```

Output:

```text
generated_arm64/
├── O0/
└── O2/
```

### RISC-V 64 Linux

Requires a RISC-V Linux cross-toolchain:

```bash
sudo apt install \
    gcc-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    libc6-dev-riscv64-cross \
    qemu-user
```

Run:

```bash
python build_riscv64_dataset.py
```

Output:

```text
generated_riscv64/
├── O0/
└── O2/
```

## Output structure

A typical generated benchmark directory is:

```text
generated_<target>/
└── O2/
    └── ackermann/
        ├── asm/
        │   └── ackermann.s
        ├── normal/
        │   └── ackermann.o
        ├── pic/
        │   └── ackermann.o
        ├── ackermann.o
        ├── ackermann.so
        ├── ackermann.program
        ├── ackermann.o.objdump
        ├── ackermann.so.objdump
        └── ackermann.program.objdump
```

The primary assembly representations used for the dataset are:

```text
asm/*.s
*.o.objdump
*.so.objdump
*.program.objdump
```

## Special case: `highlife`

At `O0`, `highlife` fails to link under the default modern GCC inline semantics because `wrap_row` and `wrap_col` are declared `inline` but may not be emitted as standalone definitions.

The generation scripts therefore compile `highlife` with:

```text
-fgnu89-inline
```

This allows both O0 and O2 builds to complete.

## Validation

Generated executables were runtime spot-checked against the expected `.out` files provided by Bringup-Bench.

Ten benchmarks were tested at both O0 and O2:

```text
ackermann
aes
anagram
bubble-sort
hanoi
n-queens
qsort-test
sieve
sudoku-solver
tea-cipher
```

### x86-64 Linux

20/20 tests matched the expected Bringup-Bench output.

### AArch64 Linux

Programs were executed using:

```bash
qemu-aarch64 -L /usr/aarch64-linux-gnu <program>
```

The generated ARM64 binaries were validated successfully.

One QEMU-specific issue was observed with the PIE build of `anagram`: guest `brk()` expansion failed under QEMU user-mode, causing `libmin_malloc()` to report an allocation failure.

A temporary non-PIE build:

```bash
aarch64-linux-gnu-gcc -no-pie ...
```

ran successfully under QEMU and matched `anagram.out` exactly, confirming that the generated ARM code and Bringup support code were correct. The dataset itself retains the normal PIE executable.

### RISC-V 64 Linux

Programs were executed using:

```bash
qemu-riscv64 -L /usr/riscv64-linux-gnu <program>
```

20/20 tests matched the expected Bringup-Bench output.

## Binary formats verified

The generated files were additionally checked with `file`.

Examples include:

```text
x86-64:
ELF 64-bit LSB relocatable, x86-64
ELF 64-bit LSB shared object, x86-64
ELF 64-bit LSB pie executable, x86-64

AArch64:
ELF 64-bit LSB relocatable, ARM aarch64
ELF 64-bit LSB shared object, ARM aarch64
ELF 64-bit LSB pie executable, ARM aarch64

RISC-V:
ELF 64-bit LSB relocatable, UCB RISC-V
ELF 64-bit LSB shared object, UCB RISC-V
ELF 64-bit LSB pie executable, UCB RISC-V
```

The corresponding `objdump` outputs were also manually inspected to confirm sensible target-specific instructions and expected linker-generated sections such as PLT/startup code in linked binaries.

## Planned Hugging Face datasets

The generated data is intended to be published separately by target:

```text
adpretko/bringup_x86_linux
adpretko/bringup_arm_linux
adpretko/bringup_riscv_linux
adpretko/bringup_arm_mac
```

Each dataset will contain O0 and O2 splits and the four code representations:

```text
compiler_asm
object_asm
shared_asm
program_asm
```

Using separate repositories avoids manually moving the generated macOS dataset onto the Linux generation machine while preserving common task names for later alignment.

