"""Install the optional approved Windows CPU assistant from verified release files."""
import argparse
import os
from pathlib import Path
import sys

from research_y.local_assistant import install_local_package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("This local inference build requires Windows x64")
    local = Path(os.environ["LOCALAPPDATA"])
    if not local.is_absolute():
        parser.error("Missing local application data location")
    destination = install_local_package(local / "RESEARCH-Y" / "models", archive=args.archive, model=args.model)
    print("Installed verified local assistant:", destination)


if __name__ == "__main__":
    main()
