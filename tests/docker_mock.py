#!/usr/bin/env python3
"""Test double for Docker command orchestration; it never builds an image."""
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] == ["--context"]:
    args = args[2:]

if args == ["context", "show"]:
    print("default")
elif args[:2] == ["context", "inspect"]:
    print("unix:///var/run/docker.sock")
elif args == ["info"]:
    pass
elif args[:2] == ["buildx", "inspect"]:
    print("Driver: docker")
elif args[:2] == ["image", "inspect"]:
    if args[args.index("--format") + 1] == "{{.Os}}/{{.Architecture}}":
        print(os.environ.get("MOCK_PLATFORM", "linux/amd64"))
    else:
        print("sha256:" + "a" * 64)
elif args[:2] == ["buildx", "build"]:
    context = Path(args[-1])
    snapshot = Path(os.environ["MOCK_SNAPSHOT"])
    shutil.copytree(context, snapshot, dirs_exist_ok=True)
    Path(os.environ["MOCK_CONTEXT_FILE"]).write_text(str(context))
    if os.environ.get("MOCK_BUILD_FAIL"):
        print("simulated Docker build failure", file=sys.stderr)
        sys.exit(23)
    Path(args[args.index("--iidfile") + 1]).write_text("sha256:" + "b" * 64)
    print("mock build (no image installation performed)")
elif args[:1] == ["create"]:
    print("mock-report-container")
elif args[:1] == ["cp"]:
    if os.environ.get("MOCK_CP_FAIL"):
        sys.exit(24)
    if args[1].endswith(":/etc/passwd"):
        Path(args[-1]).write_text(os.environ.get("MOCK_PASSWD", "root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"))
    elif args[1].endswith(":/etc/group"):
        Path(args[-1]).write_text(os.environ.get("MOCK_GROUP", "root:x:0:\nnogroup:x:65534:\n"))
    else:
        Path(args[-1]).write_text("[mock package inventory]\n")
elif args[:1] == ["rm"]:
    print("mock-report-container")
else:
    raise SystemExit(f"Unsupported mock Docker command: {args!r}")
