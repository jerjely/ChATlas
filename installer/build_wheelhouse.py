"""CI helper: resolve the pip-only dependencies inside an environment identical to the installer's
(created from construct.yaml's specs), and bundle exactly those wheels + ChATlas itself into wheelhouse.zip.

usage: python build_wheelhouse.py specs   -> prints the conda specs (one per line)
       <probe-env python> build_wheelhouse.py wheels <repo_root> <out_zip>
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

PIP_PACKAGES = ["caveclient", "cloud-volume", "crackle-codec", "compresso", "fastremap", "fast-simplification"]
HERE = os.path.dirname(os.path.abspath(__file__))


def specs():
    lines = open(os.path.join(HERE, "construct.yaml"), encoding="utf-8").read().splitlines()
    out, inside = [], False
    for ln in lines:
        if re.match(r"^specs:\s*$", ln):
            inside = True
            continue
        if inside:
            m = re.match(r"^\s+-\s+(.+?)\s*(#.*)?$", ln)
            if m:
                out.append(m.group(1))
            elif re.match(r"^\S", ln):
                break
    return out


def run(*cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(list(cmd))


def wheels(repo, out_zip):
    py = sys.executable
    before = {d["name"].lower() for d in json.loads(subprocess.check_output([py, "-m", "pip", "list", "--format=json"]))}
    run(py, "-m", "pip", "install", "--disable-pip-version-check", *PIP_PACKAGES)
    after = json.loads(subprocess.check_output([py, "-m", "pip", "list", "--format=json"]))
    added = [f"{d['name']}=={d['version']}" for d in after if d["name"].lower() not in before]
    print("pip-only packages:", added, flush=True)
    with tempfile.TemporaryDirectory() as td:
        run(py, "-m", "pip", "wheel", "--no-deps", "-w", td, *added)
        run(py, "-m", "pip", "wheel", "--no-deps", "-w", td, repo)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(td)):
                if f.endswith(".whl"):
                    z.write(os.path.join(td, f), f)
                    print("  bundled", f)
    print("wrote", out_zip)


if __name__ == "__main__":
    if sys.argv[1] == "specs":
        print("\n".join(specs()))
    else:
        wheels(sys.argv[2], sys.argv[3])
