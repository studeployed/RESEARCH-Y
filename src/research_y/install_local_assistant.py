"""Install the optional approved Windows CPU assistant from verified release files."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen

from research_y.local_assistant import install_local_package
from research_y.local_model_manifest import ENGINE_BUILD, MODEL_NAME, MODEL_REVISION, MODEL_BYTES


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


def download_local_package(parent):
    """First-use download of the two immutable release inputs, verified before activation."""
    engine = f"llama-{ENGINE_BUILD}-bin-win-cpu-x64.zip"
    sources = ((engine,f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_BUILD}/{engine}",25_097_627),
               (MODEL_NAME,f"https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/{MODEL_REVISION}/{MODEL_NAME}",MODEL_BYTES))
    with tempfile.TemporaryDirectory(prefix="research-y-model-") as tmp:
        for name,url,size in sources:
            with urlopen(url,timeout=45) as response, (Path(tmp)/name).open("xb") as output:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Model source must use HTTPS")
                remaining = size
                while remaining:
                    block = response.read(min(1024**2,remaining))
                    if not block:
                        raise ValueError("Incomplete model download")
                    output.write(block)
                    remaining -= len(block)
                if response.read(1):
                    raise ValueError("Unexpected model download size")
        return install_local_package(parent,archive=Path(tmp)/engine,model=Path(tmp)/MODEL_NAME)


if __name__ == "__main__":
    main()
