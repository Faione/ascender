#!/usr/bin/env bash
set -euo pipefail
source /etc/ascend/environment.sh
mkdir -p "$CAMODEL_HOME"
# zipfile inspects full member names (including newlines), unlike line-based CLI
# listings. Reject links and escaping paths before extracting anything.
python3 -I - /tmp/camodel-inputs "$CAMODEL_HOME" <<'PY'
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import zipfile

inputs, home = map(Path, sys.argv[1:])
archives = (inputs / "archives.txt").read_text().splitlines()
assert archives, "No CAModel archives selected"
for name in archives:
    assert Path(name).name == name and name.endswith(".zip"), name
    archive = inputs / "archives" / name
    target = home / name[:-4]
    assert not target.exists(), f"Duplicate extraction directory: {target}"
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            assert member.filename and not path.is_absolute(), member.filename
            assert ".." not in path.parts and "\\" not in member.filename, member.filename
            assert not (len(member.filename) > 1 and member.filename[1] == ":"), member.filename
            mode = member.external_attr >> 16
            assert not stat.S_ISLNK(mode), f"ZIP symlink: {member.filename}"
            assert not stat.S_IFMT(mode) or stat.S_ISREG(mode) or stat.S_ISDIR(mode), member.filename
            assert path not in seen, f"Duplicate ZIP member: {path}"
            seen.add(path)
        target.mkdir()
        package.extractall(target)
        # zipfile does not restore executable bits needed by simulator tools.
        for member in members:
            dest = target / member.filename
            if not member.is_dir():
                dest.chmod(0o755 if (member.external_attr >> 16) & 0o111 else 0o644)
for name in ("init.sh", "env.sh", "check.sh"):
    source = inputs / name
    if source.exists():
        shutil.copyfile(source, home / name)
        (home / name).chmod(0o644)
PY
cd "$CAMODEL_HOME"
for script in init.sh env.sh check.sh; do [[ ! -f "$script" ]] || bash -n "$script"; done
bash ./init.sh
unset _ASCEND_SIM_ENV_LOADED
source /etc/ascend/environment.sh
if [[ -f check.sh ]]; then
    bash ./check.sh
    sed -i 's/^simulation_validation=.*/simulation_validation=passed-build-script/' /usr/local/share/ascend/manifest.txt
else
    printf 'Simulation installed; functional validation NOT performed (no --camodel-check).\n'
fi
# Init/check scripts are allowed to customize files, so verify core versions again.
bash /usr/local/lib/ascend/verify-image.sh
