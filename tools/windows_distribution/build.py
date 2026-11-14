"""Build a self-contained, per-user Windows installer using the installed CPython and Windows SDK."""
import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def copy_runtime(image):
    base = Path(sys.base_prefix)
    for name in ("python.exe","pythonw.exe","LICENSE.txt"):
        shutil.copy2(base/name,image/name)
    for library in [*base.glob("python*.dll"),*base.glob("vcruntime*.dll")]:
        shutil.copy2(library,image/library.name)
    shutil.copytree(base/"DLLs",image/"DLLs",ignore=shutil.ignore_patterns("*.pdb","*.lib","*.exp","_test*"))
    shutil.copytree(base/"Lib",image/"Lib",ignore=shutil.ignore_patterns("site-packages","__pycache__","*.pyc"))
    if (base/"tcl").is_dir():
        shutil.copytree(base/"tcl",image/"tcl")
    (image/"launch.py").write_text("import sys\nsys.dont_write_bytecode = True\nfrom research_y.desktop.app import main\n"
                                  "if __name__ == '__main__':\n    raise SystemExit(main())\n",encoding="utf-8")


def build(destination):
    if sys.platform!="win32" or sys.version_info[:2] not in ((3,12),(3,13)) or sys.maxsize<2**32:
        raise ValueError("Use 64-bit CPython 3.12 or 3.13 on Windows")
    compiler = Path(os.environ["SystemRoot"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix="research-y-build-",dir=destination.parent) as temp:
        work = Path(temp)
        image = work/"image"
        image.mkdir()
        copy_runtime(image)
        subprocess.run([sys.executable,"-m","pip","--isolated","--disable-pip-version-check","install",
                        "--target",str(image/"Lib/site-packages"),"--no-compile","--report",str(work/"resolved.json"),
                        str(REPO)+"[desktop,pdf]"],check=True)
        for metadata in (image/"Lib/site-packages").glob("*.dist-info/direct_url.json"):
            metadata.unlink()
        shutil.rmtree(image/"Lib/site-packages/bin",ignore_errors=True)
        subprocess.run([str(image/"python.exe"),"-I","-c","from research_y.desktop.app import main; "
                        "import nicegui, webview, openpyxl, pypdf; print('Bundled runtime imports verified')"],check=True)
        common=[str(compiler),"/nologo","/target:winexe","/platform:x64","/optimize+","/r:System.Windows.Forms.dll",
                "/win32manifest:"+str(HERE/"longpaths.manifest")]
        subprocess.run([*common,"/out:"+str(image/"RESEARCH-Y.exe"),str(HERE/"Launcher.cs")],check=True)
        inventory=[dict(name=d["metadata"]["name"],version=d["metadata"]["version"],
                        license=d["metadata"].get("license_expression") or d["metadata"].get("license"),
                        sha256=d["download_info"].get("archive_info",{}).get("hashes",{}).get("sha256"))
                   for d in json.loads((work/"resolved.json").read_text(encoding="utf-8"))["install"]]
        (image/"components.json").write_text(json.dumps(dict(python=sys.version,packages=inventory),
                                                      indent=2,ensure_ascii=False),encoding="utf-8")
        archive = work/"application.zip"
        with ZipFile(archive,"x",ZIP_DEFLATED,compresslevel=6) as bundle:
            for path in sorted(image.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    bundle.write(path,path.relative_to(image).as_posix())
        with archive.open("rb") as stream:
            digest=file_digest(stream,"sha256").hexdigest()
        (work/"BuildInfo.cs").write_text('internal static class BuildInfo { public const string Image = "'+
                                        digest+'"; }',encoding="utf-8")
        staged = work/"RESEARCH-Y-Setup.exe"
        subprocess.run([*common,"/r:System.IO.Compression.dll","/r:Microsoft.CSharp.dll",
                        "/resource:"+str(archive)+",application.zip","/out:"+str(staged),
                        str(HERE/"Setup.cs"),str(work/"BuildInfo.cs")],check=True)
        os.link(staged,destination)
    return digest


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(build(args.output.resolve()))
