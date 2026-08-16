#!/usr/bin/env python3

import shlex

from datasets import load_dataset

from upload_arm64_macos_hf_reloc import (
    REPO,
    REPO_ID,
    SPLITS,
    EXPECTED_COLUMNS,
    make_var,
    build_dataset,
)


def main():
    benchmarks = shlex.split(
        make_var(REPO, "BMARKS")
    )

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, found {len(benchmarks)}"
        )

    print("=" * 72)
    print("RECONSTRUCTING LOCAL DATASET")
    print("=" * 72)

    local = build_dataset(benchmarks)

    print()
    print("=" * 72)
    print(f"LOADING HUGGING FACE DATASET")
    print(f"-> {REPO_ID}")
    print("=" * 72)

    remote = load_dataset(REPO_ID)

    if set(remote.keys()) != {"O0", "O2"}:
        raise RuntimeError(
            f"Unexpected HF splits: {list(remote.keys())}"
        )

    total = 0

    for split in SPLITS:
        local_split = local[split]
        remote_split = remote[split]

        if local_split.num_rows != 108:
            raise RuntimeError(
                f"{split}: local expected 108 rows, "
                f"found {local_split.num_rows}"
            )

        if remote_split.num_rows != 108:
            raise RuntimeError(
                f"{split}: HF expected 108 rows, "
                f"found {remote_split.num_rows}"
            )

        if remote_split.column_names != EXPECTED_COLUMNS:
            raise RuntimeError(
                f"{split}: wrong HF columns\n"
                f"expected: {EXPECTED_COLUMNS}\n"
                f"actual:   {remote_split.column_names}"
            )

        for i in range(108):
            local_row = local_split[i]
            remote_row = remote_split[i]

            for column in EXPECTED_COLUMNS:
                if not remote_row[column]:
                    raise RuntimeError(
                        f"{split}: EMPTY FIELD\n"
                        f"row: {i}\n"
                        f"problem: {local_row['problem_name']}\n"
                        f"column: {column}"
                    )

                if local_row[column] != remote_row[column]:
                    raise RuntimeError(
                        f"{split}: HF/LOCAL MISMATCH\n"
                        f"row: {i}\n"
                        f"problem: {local_row['problem_name']}\n"
                        f"column: {column}"
                    )

        print(
            f"{split}: PASS — "
            f"108/108 rows exactly match local"
        )

        total += 108

    print()
    print("=" * 72)
    print("BOTH BRINGUP MACOS HUGGING FACE DATASETS PASS")
    print(f"Exact rows verified: {total}")
    print("=" * 72)


if __name__ == "__main__":
    main()
