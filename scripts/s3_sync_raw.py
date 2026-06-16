"""Raw data S3 sync helper with AWS_PROFILE gate and confirmation prompt."""
import os
import subprocess
import sys


def main() -> None:
    direction = sys.argv[1] if len(sys.argv) > 1 else ""
    if direction not in ("upload", "download"):
        print(f"Usage: {sys.argv[0]} <upload|download>", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("AWS_PROFILE"):
        print(
            "Error: AWS_PROFILE is not set. Set it in .env or export it.",
            file=sys.stderr,
        )
        sys.exit(1)

    bucket = os.environ.get("S3_ML_DATA_BUCKET", "")
    if not bucket:
        print(
            "Error: S3_ML_DATA_BUCKET is not set. Set it in .env or pass it inline.",
            file=sys.stderr,
        )
        sys.exit(1)

    local = "data/01_raw/"
    remote = f"s3://{bucket}/01_raw/"
    profile = os.environ["AWS_PROFILE"]

    print(f"AWS_PROFILE: {profile}")

    if direction == "upload":
        confirm = input(f"Upload {local} → {remote} ? [yes/N] ")
    else:
        confirm = input(f"Download {remote} → {local} ? [yes/N] ")

    if confirm != "yes":
        print("Aborted.")
        sys.exit(1)

    if direction == "upload":
        result = subprocess.run(["aws", "s3", "sync", local, remote, "--profile", profile])
    else:
        result = subprocess.run(["aws", "s3", "sync", remote, local, "--profile", profile])

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
