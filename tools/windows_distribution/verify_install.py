"""Exercise both installer paths and retain evidence for the exact candidate."""
from hashlib import file_digest
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4


def project_evidence(folder, *, create):
    from research_y.projects import create_project, open_project
    from research_y.storage import ApprovedTerm, StrategyGroup, list_run_queries
    from research_y.strategy_admission import commit_approved_strategy
    import sqlite3
    from contextlib import closing

    if create:
        project = create_project(folder.parent,folder.name,directory_name=folder.name)
        commit_approved_strategy(project,request_id=str(uuid4()),theme="Installer upgrade example",
            groups=(StrategyGroup("group","Example",(ApprovedTerm("example","researcher",True),)),),
            approved_by="Installer test",approval_confirmed=True)
    else:
        project = open_project(folder)
    with closing(sqlite3.connect(project.database_path)) as db:
        run, = db.execute("SELECT run_id FROM search_runs").fetchall()
        strategy, = db.execute("SELECT snapshot_json FROM strategy_versions").fetchall()
    queries = list_run_queries(project,run[0])
    if len(queries) != 2:
        raise ValueError("Expected two approved source queries")
    return dict(project_id=str(project.identifier),run_id=run[0],strategy=json.loads(strategy[0]),
                queries=sorted((q.query_id,q.exact_query) for q in queries))


def install(installer, root):
    subprocess.run([installer,"--test-install-root",root],check=True,timeout=180)
    image = (root/"current.txt").read_text()
    if not re.fullmatch("[0-9a-f]{20}",image):
        raise ValueError("Invalid installed image pointer")
    return image, root/"versions"/image/"python.exe"


def verify(candidate, baseline, output):
    lifecycle = Path(__file__).resolve().parents[1]/"desktop_lifecycle.py"
    def evidence(python, action, project):
        value = subprocess.check_output([python,"-I","-B",__file__,action,project],timeout=90)
        return json.loads(value)

    with tempfile.TemporaryDirectory(prefix="ry-installer-check-") as work:
        clean = Path(work)/"clean"
        current, python = install(candidate,clean)
        subprocess.run([python,"-I","-B",lifecycle],check=True,timeout=480)
        if install(candidate,clean)[0] != current:
            raise ValueError("Reinstallation changed the selected image")
        upgrade = Path(work)/"upgrade"
        previous, old_python = install(baseline,upgrade)
        project = Path(work)/"earlier-project"
        original = evidence(old_python,"create",project)
        updated, new_python = install(candidate,upgrade)
        if current != updated or current == previous or (upgrade/"previous.txt").read_text() != previous:
            raise ValueError("Upgrade did not switch from the baseline to the candidate")
        if evidence(new_python,"read",project) != original:
            raise ValueError("Upgraded application changed the retained project or its approved queries")
        subprocess.run([new_python,"-I","-B",lifecycle],check=True,timeout=480)
        commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        baseline_commit = subprocess.check_output(["git","-C","_installer_baseline","rev-parse","HEAD"],text=True).strip()
        with candidate.open("rb") as package:
            digest = file_digest(package,"sha256").hexdigest()
        output.write_text(json.dumps(dict(commit=commit,baseline_commit=baseline_commit,
            installer_sha256=digest,bytes=candidate.stat().st_size,candidate_image=current,previous_image=previous,
            clean_install=True,reinstallation=True,upgrade=True,retained_project_and_queries=True,
            native_lifecycle_after_clean_install_and_upgrade=True),indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] in ("create","read"):
        print(json.dumps(project_evidence(Path(sys.argv[2]),create=sys.argv[1]=="create")))
    else:
        verify(*(Path(arg).resolve() for arg in sys.argv[1:]))
