"""Prepare container account copies; never read or modify host account databases."""
from dataclasses import dataclass
import os
from pathlib import Path
import re

from .errors import require


def numeric_id(value, non_root=False) -> int:
    require(bool(re.fullmatch(r"[0-9]{1,10}", str(value))), f"Invalid numeric ID: {value}")
    number = int(value)
    require(int(non_root) <= number <= 2147483647, "Use a non-root UID and a valid GID (0..2147483647).")
    return number


@dataclass(frozen=True)
class User:
    uid: int
    gid: int
    name: str = "developer"

    @classmethod
    def current(cls, uid=None, gid=None, name="developer"):
        uid = numeric_id(os.getuid() if uid is None else uid, non_root=True)
        gid = numeric_id(os.getgid() if gid is None else gid)
        require(bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", name)) and name != "root",
                "--user must be a non-root Unix username (up to 32 characters).")
        return cls(uid, gid, name)


def account_files(passwd: str, group: str, user: User) -> dict[str, str]:
    accounts, groups = passwd.splitlines(), group.splitlines()
    for row in accounts:
        fields = row.split(":")
        require(len(fields) == 7 and fields[2].isdigit(), "Malformed passwd record in image.")
        require(fields[0] != user.name or int(fields[2]) == user.uid,
                f"Username {user.name} already belongs to another UID; choose another --user.")
    for row in groups:
        fields = row.split(":")
        require(len(fields) == 4 and fields[2].isdigit(), "Malformed group record in image.")
    accounts = [row for row in accounts if int(row.split(":")[2]) != user.uid]
    accounts.append(f"{user.name}:*:{user.uid}:{user.gid}:Ascend developer:/workspace/home:/bin/bash")
    if not any(int(row.split(":")[2]) == user.gid for row in groups):
        name = f"ascend-{user.gid}"
        require(not any(row.split(":")[0] == name for row in groups), f"Group name {name} already belongs to another GID.")
        groups.append(f"{name}:*:{user.gid}:{user.name}")
    return {"passwd": "\n".join(accounts) + "\n", "group": "\n".join(groups) + "\n"}


def prepare(docker, image_id: str, user: User, directory: Path):
    """Called in a private staging directory; publication belongs to the runtime workflow."""
    directory.mkdir()
    with docker.container(image_id) as container:
        for name in ("passwd", "group"):
            docker.copy(container, f"/etc/{name}", directory / f"base-{name}")
    files = account_files((directory / "base-passwd").read_text(), (directory / "base-group").read_text(), user)
    files["identity.txt"] = f"image_id={image_id}\nuid={user.uid}\ngid={user.gid}\nuser={user.name}\n"
    for name, value in files.items():
        path = directory / name
        path.write_text(value)
        path.chmod(0o644)
