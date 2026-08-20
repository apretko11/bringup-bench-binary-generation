# Bringup-Bench Binary Dataset Generation

This repository contains the scripts used to generate binary-derived assembly datasets from the [Bringup-Bench](https://github.com/toddmaustin/bringup-bench) benchmark suite for cross-ISA translation experiments.

## Upstream source

Bringup-Bench repository:

```text
https://github.com/toddmaustin/bringup-bench
```

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

Four targets are supported:

- x86-64 Linux
- AArch64 Linux
- RISC-V 64 Linux
- ARM64 macOS

For every benchmark, artifacts are generated at both:

- `O0`
- `O2`

## Final dataset schema

Each final Hugging Face dataset row contains:

- `problem_name` - Bringup-Bench benchmark identifier
- `source_code` - benchmark C source
- `compiler_asm` - compiler-generated assembly from the normal, non-PIC compilation path
- `object_asm` - relocation-preserving disassembly of the normal relocatable object
- `shared_asm` - relocation-preserving disassembly of the linked shared library
- `program_asm` - relocation-preserving disassembly of the linked executable
- `compiler_pic_asm` - compiler-generated assembly from the PIC compilation path
- `pic_object_asm` - relocation-preserving disassembly of the PIC relocatable object

The six assembly representations belong to two distinct compilation-provenance families:

```text
NORMAL
compiler_asm
    -> object_asm
    -> program_asm

PIC
compiler_pic_asm
    -> pic_object_asm
    -> shared_asm
```

This distinction is important.

The shared library is built from separately compiled position-independent (`-fPIC`) benchmark objects. Therefore, `shared_asm` belongs to the PIC compilation lineage and should be compared against `compiler_pic_asm` and `pic_object_asm`, rather than against the normal `compiler_asm` and `object_asm` lineage.

PIC and non-PIC compilation originate from the same benchmark source and optimization level, but they are not required to produce identical optimized assembly or identical sets of compiler-generated helper functions.

## Generated representations

### Normal compiler-generated assembly

The benchmark C source is compiled directly to assembly without `-fPIC`:

```text
C source
    |
    v
compiler
    |
    v
compiler_asm
```

For multi-source benchmarks, assembly is generated for each benchmark source file.

### Normal relocatable object

The normal compilation path also produces relocatable object files:

```text
C source
    |
    v
normal object files
    |
    v
benchmark-level relocatable object
    |
    v
object_asm
```

On Linux this is an ELF relocatable object.

On macOS this is a Mach-O ARM64 relocatable object.

The final relocatable object is disassembled while preserving relocation information.

### Executable

The normal benchmark objects are linked with the Bringup-Bench support code:

```text
normal benchmark objects
        +
      libmin
        +
      libtarg
        |
        v
    executable
        |
        v
   program_asm
```

Linux targets produce ELF executables.

The macOS target produces a native ARM64 Mach-O executable.

No attempt is made during dataset generation to restrict the linked-binary disassembly to only benchmark functions. The linked executable representation preserves the assembly present in the actual linked binary.

### PIC compiler-generated assembly

The benchmark source is also compiled with `-fPIC -S`:

```text
C source
    |
    v
compiler -fPIC -S
    |
    v
compiler_pic_asm
```

This provides a compiler-generated reference from the same PIC compilation family as the shared library.

### PIC relocatable object

The PIC benchmark objects used for shared-library construction are retained and represented as a benchmark-level relocatable object:

```text
C source
    |
    v
PIC source objects
    |
    v
benchmark-level PIC relocatable object
    |
    v
pic_object_asm
```

For multi-source benchmarks, the per-source PIC objects are combined into one benchmark-level relocatable object.

The resulting object is disassembled with relocation information preserved.

### Shared library

The PIC benchmark objects are linked with the required PIC Bringup-Bench support objects.

Linux:

```text
PIC benchmark objects
        +
   PIC libmin/libtarg
        |
        v
       .so
        |
        v
   shared_asm
```

macOS:

```text
PIC benchmark objects
        +
   PIC libmin/libtarg
        |
        v
     .dylib
        |
        v
   shared_asm
```

The shared-library representation therefore belongs to the PIC provenance family.

## Relocation-preserving disassembly

The final datasets preserve relocation information in binary-derived assembly.

### Linux relocatable objects

```text
objdump -dr
```

### Linux linked shared libraries and executables

```text
objdump -drR
```

### macOS relocatable objects

```text
xcrun llvm-objdump -dr
```

### macOS linked shared libraries and executables

```text
xcrun llvm-objdump -drR
```

The relocation flags are important because plain `objdump -d` omits relocation records that are still present in relocatable objects.

## Bringup-Bench support code

Bringup-Bench supplies its own `libmin` library and target interface.

The generation scripts use the support code directly from the pinned upstream repository rather than replacing it with custom implementations.

Benchmark-specific source files, headers, and Makefile settings are retained.

The scripts query Bringup-Bench Makefile variables including:

```text
BMARKS
PROG
LOCAL_OBJS
LOCAL_CFLAGS
```

This allows benchmarks containing multiple source files or benchmark-specific compiler flags to be generated using their actual repository structure.

## Linux

### `build_x86_dataset.py`

Original x86-64 Linux generation script.

It generates the original x86-64 dataset using the earlier disassembly workflow.

It is retained for reproducibility.

### `build_x86_dataset_reloc.py`

Relocation-preserving x86-64 Linux generation script.

The corrected output is stored under:

```text
generated_x86_reloc/
```

with `O0` and `O2` subdirectories.

### `build_arm64_dataset.py`

Original AArch64 Linux generation script.

### `build_arm64_dataset_reloc.py`

Relocation-preserving AArch64 Linux generation script.

The corrected output is stored under:

```text
generated_arm64_reloc/
```

AArch64 Linux generation requires an AArch64 cross-toolchain such as:

```bash
sudo apt install \
    gcc-aarch64-linux-gnu \
    binutils-aarch64-linux-gnu \
    libc6-dev-arm64-cross \
    qemu-user
```

### `build_riscv64_dataset.py`

Original RISC-V 64 Linux generation script.

### `build_riscv64_dataset_reloc.py`

Relocation-preserving RISC-V 64 Linux generation script.

The corrected output is stored under:

```text
generated_riscv64_reloc/
```

RISC-V Linux generation requires a RISC-V cross-toolchain such as:

```bash
sudo apt install \
    gcc-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    libc6-dev-riscv64-cross \
    qemu-user
```

### `validate_linux_reloc.py`

Validates the locally generated relocation-preserving Linux datasets.

The validation checks include:

- expected benchmark and optimization-level coverage
- source preservation
- generated artifact structure
- target binary formats
- relocation-preserving disassembly
- consistency with the intended `-dr` and `-drR` commands

### `add_pic_references_linux.py`

Adds the explicit PIC compiler and PIC relocatable-object references required by the final eight-column datasets.

For each benchmark and optimization level it adds PIC compiler assembly under:

```text
pic_asm/
```

and produces a benchmark-level PIC relocatable object and its relocation-preserving disassembly:

```text
<program>.pic.o
<program>.pic.o.objdump
```

For a single-source benchmark, the existing PIC benchmark object can be used directly as the benchmark-level PIC object.

For a multi-source benchmark, the existing per-source PIC objects are combined into a single relocatable PIC object before disassembly.

The script reuses the PIC objects already produced for shared-library construction rather than rebuilding the shared-library lineage.

This preserves the provenance:

```text
compiler_pic_asm
    -> pic_object_asm
    -> shared_asm
```

### `upload_linux_hf.py`

Original Linux Hugging Face packaging/upload script.

It is retained for reproducibility of the earlier dataset-generation workflow.

### `upload_linux_hf_with_pic.py`

Packages and uploads the final eight-column Linux datasets.

The schema is:

```text
problem_name
source_code
compiler_asm
object_asm
shared_asm
program_asm
compiler_pic_asm
pic_object_asm
```

The final Linux repositories are:

```text
adpretko/bringup_x86_linux_reloc
adpretko/bringup_arm_linux_reloc
adpretko/bringup_riscv_linux_reloc
```

The final datasets contain both `O0` and `O2` splits.

## ARM64 macOS

ARM64 macOS generation was validated on Apple Silicon using Apple Clang and `xcrun llvm-objdump`.

The macOS toolchain uses:

```text
clang
ar
xcrun
llvm-objdump
```

### `build_arm64_macos_dataset.py`

Original ARM64 macOS generation script.

The original output is stored under:

```text
generated_arm64_mac/
```

with `O0` and `O2` subdirectories.

The original macOS generator automatically applies a small compatibility patch to the pinned Bringup-Bench source before compilation.

The upstream Clang-specific definition in `target/libtarg.h` is:

```c
typedef signed __SIZE_TYPE__ ssize_t;
```

Apple Clang defines:

```text
__SIZE_TYPE__    = long unsigned int
__PTRDIFF_TYPE__ = long int
```

so the upstream declaration is invalid on this toolchain.

The macOS generator replaces it with:

```c
typedef __PTRDIFF_TYPE__ ssize_t;
```

The compatibility patch is applied automatically and idempotently.

### `build_arm64_macos_dataset_reloc.py`

Relocation-preserving ARM64 macOS generation script used for the final dataset lineage.

This script is also used as a dependency by the PIC-reference enrichment workflow.

It preserves the benchmark-aware build logic required for:

- benchmark source discovery
- Makefile-derived object lists
- benchmark-specific flags
- normal object construction
- PIC object construction
- shared-library construction
- executable construction
- multi-source benchmark handling

The final relocation-preserving macOS artifacts are stored under the `_reloc` output tree.

### Why macOS uses a refresh workflow

Mach-O dynamic libraries contain an `LC_ID_DYLIB` load command.

Rebuilding a dylib under a different filesystem path can change the embedded dylib path, alter the load-command size, and shift the resulting Mach-O layout even when the source and intended compiler options are otherwise unchanged.

For the relocation-preserving correction workflow, existing binary artifacts are therefore retained where appropriate and their binary-derived text is regenerated using relocation-preserving disassembly.

### `refresh_arm64_macos_objdump_reloc.py`

Refreshes relocation-aware objdump text for existing ARM64 macOS artifacts.

Relocatable objects use:

```text
xcrun llvm-objdump -dr
```

Linked dylibs and executables use:

```text
xcrun llvm-objdump -drR
```

### `validate_arm64_macos_reloc.py`

Validates the relocation-preserving ARM64 macOS output.

The checks include:

- expected benchmark coverage
- expected `O0` and `O2` splits
- output-tree consistency
- preservation of the intended binary artifacts
- fresh relocation-aware disassembly agreement
- ARM64 Mach-O binary formats

### `add_pic_references_bringup_arm64_macos.py`

Adds the explicit PIC reference artifacts required by the final macOS dataset.

For each benchmark and optimization level it generates PIC compiler assembly under:

```text
pic_asm/
```

and creates a benchmark-level PIC relocatable object:

```text
<program>.pic.o
```

For multi-source benchmarks, the existing PIC benchmark objects are combined with:

```text
clang -arch arm64 -r
```

The resulting PIC relocatable object is disassembled with:

```text
xcrun llvm-objdump -dr
```

to produce:

```text
<program>.pic.o.objdump
```

The script reuses the existing PIC source objects from the relocation-preserving build rather than recompiling the shared-library lineage.

### `package_arm64_macos_hf.py`

Original ARM64 macOS Hugging Face packaging script.

It is retained for reproducibility of the earlier workflow.

### `upload_arm64_macos_hf_reloc.py`

Uploads the earlier relocation-preserving ARM64 macOS dataset representation.

It predates the addition of the explicit PIC compiler/object reference columns and is retained for reproducibility.

### `upload_bringup_arm64_macos_hf_with_pic.py`

Produces the final eight-column ARM64 macOS dataset.

The final schema is:

```text
problem_name
source_code
compiler_asm
object_asm
shared_asm
program_asm
compiler_pic_asm
pic_object_asm
```

The target repository is:

```text
adpretko/bringup_arm_mac_reloc
```

The script validates the existing live relocation-preserving dataset against the corresponding local artifact tree before appending:

```text
compiler_pic_asm
pic_object_asm
```

It supports validation without uploading:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py --validate-only
```

It can also reload and verify the final live Hugging Face dataset:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py --verify-live
```

### `validate_arm64_macos_hf.py`

Validation utility retained from the earlier macOS Hugging Face workflow.

The final PIC-aware live dataset can additionally be verified directly with:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py --verify-live
```

## Output structure

A representative final Linux benchmark directory is:

```text
generated_<target>_reloc/
└── O2/
    └── ackermann/
        ├── asm/
        │   └── ackermann.s
        ├── pic_asm/
        │   └── ackermann.s
        ├── normal/
        │   └── ...
        ├── pic/
        │   └── ...
        ├── ackermann.o
        ├── ackermann.o.objdump
        ├── ackermann.pic.o
        ├── ackermann.pic.o.objdump
        ├── ackermann.so
        ├── ackermann.so.objdump
        ├── ackermann.program
        └── ackermann.program.objdump
```

The corresponding macOS output uses:

```text
ackermann.dylib
ackermann.dylib.objdump
```

instead of:

```text
ackermann.so
ackermann.so.objdump
```

The final six assembly representations are therefore derived from:

```text
NORMAL

asm/*.s
<program>.o.objdump
<program>.program.objdump


PIC

pic_asm/*.s
<program>.pic.o.objdump
<program>.so.objdump       # Linux
<program>.dylib.objdump    # macOS
```

## Special case: `highlife`

At `O0`, `highlife` fails to link under the default modern compiler inline semantics because `wrap_row` and `wrap_col` are declared `inline` but may not be emitted as standalone definitions.

The generation scripts therefore compile `highlife` with:

```text
-fgnu89-inline
```

This allows both `O0` and `O2` builds to complete.

## Runtime validation

The generated executables were runtime spot-checked against the expected `.out` files supplied by Bringup-Bench.

Ten benchmarks were tested at both `O0` and `O2`:

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

20/20 runtime tests matched the expected Bringup-Bench output.

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

ran successfully under QEMU and matched `anagram.out`, confirming that the generated ARM code and Bringup support code were correct.

The dataset itself retains the normal PIE executable.

### RISC-V 64 Linux

Programs were executed using:

```bash
qemu-riscv64 -L /usr/riscv64-linux-gnu <program>
```

20/20 runtime tests matched the expected Bringup-Bench output.

### ARM64 macOS

Executables were run natively on Apple Silicon.

20/20 runtime tests matched the expected Bringup-Bench output.

The `O0` and `O2` disassemblies of `ackermann` and `anagram` were also manually inspected across the binary-derived representations.

The resulting code contained sensible ARM64 instructions and the expected structural differences between relocatable and fully linked Mach-O binaries.

## Binary formats verified

Generated files were additionally checked with `file`.

Representative formats include:

```text
x86-64 Linux:
ELF 64-bit LSB relocatable, x86-64
ELF 64-bit LSB shared object, x86-64
ELF 64-bit LSB pie executable, x86-64

AArch64 Linux:
ELF 64-bit LSB relocatable, ARM aarch64
ELF 64-bit LSB shared object, ARM aarch64
ELF 64-bit LSB pie executable, ARM aarch64

RISC-V Linux:
ELF 64-bit LSB relocatable, UCB RISC-V
ELF 64-bit LSB shared object, UCB RISC-V
ELF 64-bit LSB pie executable, UCB RISC-V

ARM64 macOS:
Mach-O 64-bit object arm64
Mach-O 64-bit dynamically linked shared library arm64
Mach-O 64-bit executable arm64
```

The corresponding disassembly outputs were inspected to confirm sensible target-specific instructions and expected differences between relocatable objects, shared libraries, and executables.

## Final provenance model

The final dataset should be interpreted as two related but separate compilation paths:

```text
                 NORMAL COMPILATION

source_code
    |
    +--> compiler_asm
            |
            +--> object_asm
                    |
                    +--> program_asm


                   PIC COMPILATION

source_code
    |
    +--> compiler_pic_asm
            |
            +--> pic_object_asm
                    |
                    +--> shared_asm
```

The same benchmark source and optimization level feed both paths.

However, position-independent code generation can change instruction selection, addressing, symbol access, calls, optimization decisions, and even the set of compiler-generated helper functions.

For that reason, normal and PIC representations should not be treated as a single linear sequence or required to have identical optimized structure.

## Hugging Face datasets

The final relocation-preserving datasets are:

```text
adpretko/bringup_x86_linux_reloc
adpretko/bringup_arm_linux_reloc
adpretko/bringup_riscv_linux_reloc
adpretko/bringup_arm_mac_reloc
```

Each repository contains:

```text
O0
O2
```

with the final eight-column schema:

```text
problem_name
source_code
compiler_asm
object_asm
shared_asm
program_asm
compiler_pic_asm
pic_object_asm
```

Using separate repositories allows each ISA/platform dataset to be generated and uploaded from the appropriate host while retaining common benchmark names for later alignment.

## Recommended workflow

### Linux

Run the appropriate relocation-preserving builder:

```bash
python build_x86_dataset_reloc.py
```

or:

```bash
python build_arm64_dataset_reloc.py
```

or:

```bash
python build_riscv64_dataset_reloc.py
```

Validate the generated relocation-preserving data:

```bash
python validate_linux_reloc.py
```

Generate the explicit PIC compiler/object references:

```bash
python add_pic_references_linux.py
```

Validate final Hugging Face packaging without uploading:

```bash
python upload_linux_hf_with_pic.py --validate-only
```

Upload the final Linux datasets:

```bash
python upload_linux_hf_with_pic.py
```

### ARM64 macOS

Generate the relocation-preserving ARM64 macOS dataset:

```bash
python3 build_arm64_macos_dataset_reloc.py
```

Refresh relocation-preserving disassembly where required:

```bash
python3 refresh_arm64_macos_objdump_reloc.py
```

Validate the local relocation-preserving output:

```bash
python3 validate_arm64_macos_reloc.py
```

Generate the explicit PIC compiler/object references:

```bash
python3 add_pic_references_bringup_arm64_macos.py
```

Validate final Hugging Face packaging without uploading:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py --validate-only
```

Upload the final eight-column dataset:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py
```

Verify the final live Hugging Face dataset:

```bash
python3 upload_bringup_arm64_macos_hf_with_pic.py --verify-live
```

## Reproducibility note

The original generation, packaging, upload, and validation scripts are intentionally retained.

They document the progression from:

```text
original binary generation
        ->
relocation-preserving disassembly
        ->
explicit normal/PIC provenance
```

The final `_reloc` Hugging Face datasets contain the complete eight-column representation and should be used for the current cross-ISA translation experiments.
