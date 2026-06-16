"""Golden dataset DVC push/pull helper with AWS_PROFILE gate and upload confirmation."""
import os
import subprocess
import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in ("push", "pull"):
        print(f"Usage: {sys.argv[0]} <push|pull>", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("AWS_PROFILE"):
        print(
            f"Error: AWS_PROFILE is not set."
            f" Set it via: AWS_PROFILE=<profile> make golden-dataset-{command}",
            file=sys.stderr,
        )
        sys.exit(1)

    if command == "push":
        remote_url = ""
        try:
            with open(".dvc/config") as f:
                for line in f:
                    if "url" in line and "=" in line:
                        remote_url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass

        print()
        print(f"  data/golden-dataset  →  {remote_url}")
        print(f"  AWS_PROFILE          :  {os.environ['AWS_PROFILE']}")
        print()
        confirm = input("  Upload? [yes/N] ")
        if confirm != "yes":
            print("  Aborted.")
            sys.exit(1)

    result = subprocess.run(["dvc", command, "data/golden-dataset.dvc"])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
