"""[B] python -m generator.seed --source olist|synthetic

Hai chế độ cùng một đầu ra (contracts/schemas). Seed cố định để chạy lại ra đúng cùng dữ liệu.
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["olist", "synthetic"], default="synthetic")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    # TODO(B): gọi olist_loader / synthetic, inject, statements.
    raise NotImplementedError(f"seed source={args.source} seed={args.seed}")


if __name__ == "__main__":
    main()
