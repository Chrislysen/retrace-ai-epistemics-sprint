"""Bundle the local prototype and audit records, excluding secrets/caches/Git."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
excluded = {".git", "__pycache__", ".venv", "node_modules", "deliverables", ".retrace"}
paths = []
for path in sorted(ROOT.rglob("*")):
    relative = path.relative_to(ROOT)
    if not path.is_file() or any(part in excluded for part in relative.parts) or path.name.startswith(".env"):
        continue
    if path.suffix in {".pyc", ".log"} or relative.as_posix() == "results/artifact-manifest.json":
        continue
    content = path.read_bytes()
    if re.search(rb"pt_live_[A-Za-z0-9]{20,}", content):
        raise RuntimeError(f"Credential pattern found in {relative}; refusing to package")
    paths.append((path, relative, content))
manifest = {"schema": "retrace.artifact.v1", "files": [{"path": relative.as_posix(), "bytes": len(content),
              "sha256": hashlib.sha256(content).hexdigest()} for _, relative, content in paths],
            "note": "Integrity inventory of this local build, not an external timestamp or authentication of evidence."}
manifest_path = ROOT / "results" / "artifact-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
destination = ROOT / "deliverables" / "RETRACE-prototype.zip"
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for _, relative, content in paths:
        archive.writestr(relative.as_posix(), content)
    archive.write(manifest_path, "results/artifact-manifest.json")
print(json.dumps({"archive": str(destination), "files": len(paths) + 1, "bytes": destination.stat().st_size,
                  "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}, indent=2))
