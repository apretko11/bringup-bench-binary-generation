#!/usr/bin/env python3

from datasets import load_dataset

from upload_linux_hf import (
    TARGETS,
    SPLITS,
    EXPECTED_COLUMNS,
    make_var,
    build_dataset_dict,
    REPO,
)

import shlex


def main():
    benchmarks = shlex.split(make_var(REPO, "BMARKS"))

    if len(benchmarks) != 108:
        raise RuntimeError(
            f"Expected 108 benchmarks, found {len(benchmarks)}"
        )

    total = 0

    for target_name, config in TARGETS.items():
        repo_id = config["repo_id"]

        print()
        print("=" * 72)
        print(f"VERIFYING {target_name}")
        print(f"HF repo: {repo_id}")
        print("=" * 72)

        # Reconstruct the already-validated local DatasetDict.
        local = build_dataset_dict(
            config["generated"],
            benchmarks,
        )

        # Load the copy that actually landed on Hugging Face.
        remote = load_dataset(repo_id)

        if set(remote.keys()) != {"O0", "O2"}:
            raise RuntimeError(
                f"{repo_id}: unexpected splits: {list(remote.keys())}"
            )

        for opt in SPLITS:
            local_split = local[opt]
            remote_split = remote[opt]

            if remote_split.num_rows != 108:
                raise RuntimeError(
                    f"{repo_id} {opt}: expected 108 rows, "
                    f"found {remote_split.num_rows}"
                )

            if remote_split.column_names != EXPECTED_COLUMNS:
                raise RuntimeError(
                    f"{repo_id} {opt}: wrong columns:\n"
                    f"{remote_split.column_names}"
                )

            if local_split.num_rows != remote_split.num_rows:
                raise RuntimeError(
                    f"{repo_id} {opt}: local/remote row-count mismatch"
                )

            # Exact row-by-row, column-by-column comparison.
            for i in range(local_split.num_rows):
                local_row = local_split[i]
                remote_row = remote_split[i]

                for column in EXPECTED_COLUMNS:
                    if local_row[column] != remote_row[column]:
                        raise RuntimeError(
                            f"{repo_id} {opt}: MISMATCH\n"
                            f"  row: {i}\n"
                            f"  problem: "
                            f"{local_row['problem_name']}\n"
                            f"  column: {column}"
                        )

                    if not remote_row[column]:
                        raise RuntimeError(
                            f"{repo_id} {opt}: EMPTY FIELD\n"
                            f"  row: {i}\n"
                            f"  column: {column}"
                        )

            print(
                f"{opt}: PASS — 108/108 rows exactly match local"
            )

            total += remote_split.num_rows

    print()
    print("=" * 72)
    print("ALL SIX HUGGING FACE DATASETS PASS")
    print(f"Exact rows verified: {total}")
    print("=" * 72)


if __name__ == "__main__":
    main()
