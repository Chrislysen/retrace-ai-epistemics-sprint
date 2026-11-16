#!/usr/bin/env python3
"""Inventory of the RETRACE working copy.

Sprint addition, written with AI assistance on Sunday 15 November 2026.
Standard library only. It reads file metadata and file bytes (for hashing) and never
parses the content of a result file. It writes only under post_sweep/ and paper_build/.

    python post_sweep/inventory.py classify     split files into tracked / kept out of git
    python post_sweep/inventory.py hashes       SHA-256 of every file kept out of git
    python post_sweep/inventory.py manifest data/frontier-v6n-freeze.json
    python post_sweep/inventory.py timestamps   prior-work table from file times
"""
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "post_sweep" / "out"

# Folders created by this session, or private to it. Everything else came with the copy.
OWN_TOP = {".git", ".venv-fable", ".claude", "paper_build", "post_sweep", "prereg", "baseline", "lints"}
# Kept out of git: whole folders of run output, and any single file of 1 MiB or more.
BULK_TOP = {"results", "deliverables"}
BULK_MIN_BYTES = 1 << 20

# The first copy was made at 21:54 on Sunday 15 November. Its newest file was written at
# 17:39:20, it skipped folders named frontier-v6m* / frontier-v6n*, and it skipped files over
# 50 MiB. The user copied the final results in at 22:31. A file is counted as a 22:31 arrival
# if it could not have been in the first copy.
FIRST_COPY_NEWEST = datetime(2026, 11, 15, 17, 39, 20)
FIRST_COPY_SIZE_LIMIT = 52_428_800
SPRINT_FRIDAY = datetime(2026, 11, 13, 0, 0, 0)  # local time (CET)

TAG = re.compile(r"(?<![a-z0-9])v(\d+[a-z]?)(?![a-z0-9])")


def is_secret(name):
    n = name.lower()
    return n == "secrets.local.env" or n.endswith(".env") or n.startswith(".env")


def original_files():
    """Yield (posix relative path, Path, stat) for every file that came with the copy."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT)
        top_level = rel_dir == Path(".")
        if top_level:
            dirnames[:] = sorted(d for d in dirnames if d not in OWN_TOP)
        else:
            dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = name if top_level else (rel_dir / name).as_posix()
            yield rel, path, path.stat()


def created(st):
    return datetime.fromtimestamp(getattr(st, "st_birthtime", None) or st.st_ctime)


def written(st):
    return datetime.fromtimestamp(st.st_mtime)


def arrived_2231(rel, st):
    folders = rel.lower().split("/")[:-1]
    in_skipped_folder = any(f.startswith(("frontier-v6m", "frontier-v6n")) for f in folders)
    return in_skipped_folder or st.st_size > FIRST_COPY_SIZE_LIMIT or written(st) > FIRST_COPY_NEWEST


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_ignored(paths):
    """Paths matched by the .gitignore that came with the copy."""
    if not paths:
        return set()
    data = "\0".join(paths).encode("utf-8") + b"\0"
    run = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "-z", "--stdin"],
                         input=data, capture_output=True)
    if run.returncode not in (0, 1):
        raise SystemExit(run.stderr.decode("utf-8", "replace"))
    return {p for p in run.stdout.decode("utf-8").split("\0") if p}


def escape_exclude(rel):
    return "/" + re.sub(r"([\\*?\[\]#! ])", r"\\\1", rel)


def classify():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(original_files())
    reasons = {}
    for rel, _, st in rows:
        top = rel.split("/")[0]
        if is_secret(rel.split("/")[-1]):
            reasons[rel] = "secret-not-read"
        elif top in BULK_TOP:
            reasons[rel] = "bulk-folder"
        elif st.st_size >= BULK_MIN_BYTES:
            reasons[rel] = "large-file"
    for rel in git_ignored([rel for rel, _, _ in rows if rel not in reasons]):
        reasons[rel] = "ignored-by-project-gitignore"
    tracked = [rel for rel, _, _ in rows if rel not in reasons]
    size = {rel: st.st_size for rel, _, st in rows}

    (OUT / "tracked_paths.nul").write_bytes(("\0".join(tracked) + "\0").encode("utf-8"))
    with open(OUT / "untracked_original.tsv", "w", encoding="utf-8", newline="\n") as handle:
        for rel in sorted(reasons):
            handle.write(f"{reasons[rel]}\t{size[rel]}\t{rel}\n")
    with open(OUT / "git_exclude_additions.txt", "w", encoding="utf-8", newline="\n") as handle:
        for top in sorted(BULK_TOP):
            handle.write(f"/{top}/\n")
        for rel in sorted(r for r, why in reasons.items() if why == "large-file"):
            handle.write(escape_exclude(rel) + "\n")
    arrivals = [(rel, st) for rel, _, st in rows if arrived_2231(rel, st)]
    with open(OUT / "arrivals_2231.tsv", "w", encoding="utf-8", newline="\n") as handle:
        for rel, st in arrivals:
            handle.write(f"{st.st_size}\t{written(st):%Y-%m-%d %H:%M:%S}\t{rel}\n")

    print(f"files that came with the copy: {len(rows)}  ({sum(size.values()):,} bytes)")
    print(f"tracked in git: {len(tracked)}  ({sum(size[r] for r in tracked):,} bytes)")
    for why, count in sorted(Counter(reasons.values()).items()):
        total = sum(size[r] for r, w in reasons.items() if w == why)
        print(f"kept out of git, {why}: {count}  ({total:,} bytes)")
    print(f"22:31 arrivals: {len(arrivals)}  ({sum(st.st_size for _, st in arrivals):,} bytes); "
          f"of these tracked: {sum(1 for rel, _ in arrivals if rel not in reasons)}")


def hashes():
    lines, total = [], 0
    with open(OUT / "untracked_original.tsv", encoding="utf-8") as handle:
        for line in handle:
            why, size, rel = line.rstrip("\n").split("\t", 2)
            if why == "secret-not-read":
                continue
            lines.append(f"{sha256(ROOT / rel)}  {rel}")
            total += int(size)
    target = ROOT / "post_sweep" / "baseline_hashes.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"hashed {len(lines)} files ({total:,} bytes) into {target.relative_to(ROOT).as_posix()}")


def hashes_new(label):
    """After a later export: hash the untracked files that were not in the earlier hash lists."""
    known = set()
    for earlier in sorted((ROOT / "post_sweep").glob("*hashes*.txt")):
        known |= {line.split("  ", 1)[1] for line in earlier.read_text(encoding="utf-8").splitlines() if "  " in line}
    lines, total = [], 0
    with open(OUT / "untracked_original.tsv", encoding="utf-8") as handle:
        for line in handle:
            why, size, rel = line.rstrip("\n").split("\t", 2)
            if why == "secret-not-read" or rel in known:
                continue
            lines.append(f"{sha256(ROOT / rel)}  {rel}")
            total += int(size)
    target = ROOT / "post_sweep" / f"export_hashes_{label}.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"hashed {len(lines)} new files ({total:,} bytes) into {target.relative_to(ROOT).as_posix()}")


def manifest(rel_manifest):
    path = ROOT / rel_manifest
    listed = json.loads(path.read_text(encoding="utf-8"))["files"]
    missing, differ, match = [], [], 0
    for entry in listed:
        target = ROOT / entry["path"]
        if not target.is_file():
            missing.append(entry["path"])
        elif sha256(target) != entry["sha256"]:
            differ.append(entry["path"])
        else:
            match += 1
    result = {
        "manifest": rel_manifest,
        "manifest_sha256": sha256(path),
        "checked_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "listed": len(listed), "match": match, "differ": len(differ), "missing": len(missing),
        "differ_paths": differ, "missing_paths": missing,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"manifest_check_{Path(rel_manifest).stem}.json"
    target.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    print({k: v for k, v in result.items() if not k.endswith("_paths")})
    for label, paths in (("DIFFER", differ), ("MISSING", missing)):
        for p in paths[:20]:
            print(f"  {label}  {p}")


def timestamps():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [(rel, st.st_size, created(st), written(st)) for rel, _, st in original_files()]
    with open(OUT / "file_times.csv", "w", encoding="utf-8", newline="") as handle:
        out = csv.writer(handle, lineterminator="\n")
        out.writerow(["path", "bytes", "created_local", "last_written_local"])
        for rel, size, c, w in rows:
            out.writerow([rel, size, f"{c:%Y-%m-%d %H:%M:%S}", f"{w:%Y-%m-%d %H:%M:%S}"])

    def table(groups, first_column):
        head = (f"| {first_column} | Files | Created before Fri 13 Nov | Written before Fri 13 Nov | "
                "Earliest created | Earliest written | Latest written | Fri 13 | Sat 14 | Sun 15 |")
        lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
        for name, items in groups:
            days = Counter(w.strftime("%d") for _, _, _, w in items)
            lines.append(
                f"| `{name}` | {len(items)} | {sum(c < SPRINT_FRIDAY for _, _, c, _ in items)} | "
                f"{sum(w < SPRINT_FRIDAY for _, _, _, w in items)} | "
                f"{min(c for _, _, c, _ in items):%a %H:%M:%S} | {min(w for _, _, _, w in items):%a %H:%M:%S} | "
                f"{max(w for _, _, _, w in items):%a %H:%M:%S} | {days.get('13', 0)} | {days.get('14', 0)} | {days.get('15', 0)} |")
        return lines

    by_area, by_tag = defaultdict(list), defaultdict(list)
    for row in rows:
        rel = row[0]
        by_area[rel.split("/")[0] + "/" if "/" in rel else "(top-level files)"].append(row)
        found = TAG.search(rel.lower())
        by_tag["v" + found.group(1) if found else "(no version tag)"].append(row)
    areas = sorted(by_area.items())
    tags = sorted(by_tag.items(), key=lambda kv: min(w for _, _, _, w in kv[1]))
    copied_inside = sum((c - w).total_seconds() > 2 for _, _, c, w in rows)
    oldest_c = min(rows, key=lambda r: r[2])
    oldest_w = min(rows, key=lambda r: r[3])
    newest_w = max(rows, key=lambda r: r[3])

    text = [
        "# File times in the working copy",
        "",
        f"Produced by `post_sweep/inventory.py timestamps` at {datetime.now():%Y-%m-%d %H:%M:%S} local time (CET).",
        "Per-file values are in `post_sweep/out/file_times.csv`. Folders created by the Claude Code session are left out.",
        "",
        f"- Files: {len(rows)}.",
        f"- Oldest creation time: {oldest_c[2]:%A %d %B %Y %H:%M:%S}, `{oldest_c[0]}`.",
        f"- Oldest last-write time: {oldest_w[3]:%A %d %B %Y %H:%M:%S}, `{oldest_w[0]}`.",
        f"- Newest last-write time: {newest_w[3]:%A %d %B %Y %H:%M:%S}, `{newest_w[0]}`.",
        f"- Files created before Friday 13 November 2026: {sum(c < SPRINT_FRIDAY for _, _, c, _ in rows)}.",
        f"- Files last written before Friday 13 November 2026: {sum(w < SPRINT_FRIDAY for _, _, _, w in rows)}.",
        f"- Files whose creation time is more than two seconds later than their last write: {copied_inside}. "
        "That pattern is what a copy inside the folder leaves behind.",
        "",
        "## By top-level area",
        "",
        *table(areas, "Area"),
        "",
        "## By version tag in the path, in order of first write",
        "",
        "The tag is the first `vN` or `vNx` in the path, for example `frontier_v6l_eval.py` gives `v6l`.",
        "",
        *table(tags, "Tag"),
        "",
    ]
    target = ROOT / "paper_build" / "prior_work_timestamps.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(text), encoding="utf-8", newline="\n")
    print("\n".join(text[4:12]))
    print(f"wrote {target.relative_to(ROOT).as_posix()} and post_sweep/out/file_times.csv")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "classify":
        classify()
    elif command == "hashes":
        hashes()
    elif command == "hashes-new" and len(sys.argv) == 3:
        hashes_new(sys.argv[2])
    elif command == "manifest" and len(sys.argv) == 3:
        manifest(sys.argv[2])
    elif command == "timestamps":
        timestamps()
    else:
        raise SystemExit(__doc__)
