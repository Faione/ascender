"""ZIP validation/extraction shared by host checks and container installation.

This module is self-contained: the build copies it into the image's script directory.
"""
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


def members(package):
    seen = set()
    for member in package.infolist():
        path = PurePosixPath(member.filename)
        mode = member.external_attr >> 16
        if (not member.filename or path.is_absolute() or ".." in path.parts
                or "\\" in member.filename or (len(member.filename) > 1 and member.filename[1] == ":")):
            raise ValueError(f"Unsafe ZIP entry: {member.filename}")
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
            raise ValueError(f"Unsupported ZIP entry type: {member.filename}")
        if path in seen:
            raise ValueError(f"Duplicate ZIP member: {path}")
        seen.add(path)
        yield member, path


def validate(archives):
    """Read CRCs and validate the merged namespace before writing any archive content."""
    paths = {}
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as package:
                for member, path in members(package):
                    for parent in path.parents:
                        if paths.get(parent) is False:
                            raise ValueError(f"ZIP file/directory conflict: {parent}")
                        paths[parent] = True
                    if path in paths and not (paths[path] and member.is_dir()):
                        raise ValueError(f"Conflicting ZIP entry: {path}")
                    paths[path] = member.is_dir()
                corrupt = package.testzip()
                if corrupt:
                    raise ValueError(f"Invalid ZIP CRC: {archive}: {corrupt}")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
            raise ValueError(f"Invalid ZIP: {archive}: {error}") from error


def extract(archives, destination):
    """Merge into a fresh installation tree; preserve executable bits, refuse overwrites."""
    validate(archives)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for archive in archives:
        with zipfile.ZipFile(archive) as package:
            for member, path in members(package):
                target = destination / path
                # Existing parents must be real directories, never links.
                for parent in (target, *target.parents):
                    if parent == destination.parent:
                        break
                    if parent.is_symlink():
                        raise ValueError(f"ZIP destination is a symlink: {parent}")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o755 if (member.external_attr >> 16) & 0o111 else 0o644)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract staged CAModel ZIPs directly into CAMODEL_HOME.")
    parser.add_argument("inputs", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    names = (args.inputs / "archives.txt").read_text().splitlines()
    if not names or any(Path(name).name != name or not name.endswith(".zip") for name in names):
        parser.error("Expected a list of ZIP basenames.")
    extract([args.inputs / "archives" / name for name in names], args.destination)
    for name in ("init.sh", "env.sh", "check.sh"):
        source = args.inputs / name
        if source.exists():
            target = args.destination / name
            if target.is_symlink():
                raise ValueError(f"Script destination is a symlink: {target}")
            shutil.copyfile(source, target)
            target.chmod(0o644)
