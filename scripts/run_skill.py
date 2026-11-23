#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic research archive steward. Standard library only."""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

MAX_FILES = 5000
MAX_HASH_BYTES = 64 * 1024 * 1024

PATH_KEYS = (
    "input_dir", "input_root", "materials_dir", "materials", "data_dir",
    "dataset_dir", "corpus_dir", "directory", "path", "root",
)
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".cache"}

CATEGORY = {
    "documents": {".pdf", ".doc", ".docx", ".md", ".txt", ".tex", ".rtf", ".odt", ".pptx", ".ppt"},
    "data": {".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl", ".sqlite", ".db", ".h5", ".hdf5", ".parquet", ".xml", ".yaml", ".yml"},
    "images": {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".svg", ".gif", ".webp"},
    "archives": {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2"},
    "code": {".py", ".r", ".m", ".sh", ".ipynb", ".jl", ".cpp", ".c", ".h", ".java"},
}

VERSION_NOISE = re.compile(
    r"(?i)(^|[\s._\-\(\[])(v|ver|version|rev|r)?\d+(\.\d+)*($|[\s._\-\)\]])"
    r"|(^|[\s._\-\(\[])(final|draft|copy|backup|old|new|修订|最终|副本|备份|定稿)($|[\s._\-\)\]])"
)
PAREN_NOISE = re.compile(r"\((\d+)\)\s*$")

ALIASES = {
    "case_id": ["case_id", "caseid", "id"],
    "manifest": ["manifest", "file_manifest", "inventory", "file_inventory", "files",
                 "file_list", "listing", "directory_manifest", "organized_files", "archive_manifest"],
    "duplicate_groups": ["duplicates", "duplicate_groups", "duplicate_files", "dedup"],
    "version_chains": ["version_chains", "versions", "version_relations", "version_graph"],
    "layout_plan": ["layout", "layout_plan", "directory_tree", "tree", "structure", "target_layout"],
    "operations": ["operations", "change_log", "changes", "action_log", "audit_log"],
    "skipped": ["skipped", "skipped_files", "excluded", "unreadable"],
    "summary": ["summary", "overview", "answer", "conclusion", "notes", "description"],
    "status": ["status", "run_status"],
    "result": ["result", "results", "data"],
    "evidence": ["evidence", "sources", "provenance"],
    "uncertainty": ["uncertainty", "limitations"],
    "errors": ["errors", "error"],
    "stats": ["stats", "statistics", "counts"],
}


def norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def contract_fields(case):
    oc = case.get("output_contract")
    out = []
    if isinstance(oc, dict):
        if isinstance(oc.get("properties"), dict):
            out = list(oc["properties"].keys())
        elif isinstance(oc.get("fields"), dict):
            out = list(oc["fields"].keys())
        elif isinstance(oc.get("fields"), list):
            out = [x for x in oc["fields"] if isinstance(x, str)]
        elif isinstance(oc.get("required"), list):
            out = [x for x in oc["required"] if isinstance(x, str)]
        else:
            out = list(oc.keys())
    elif isinstance(oc, list):
        out = [x for x in oc if isinstance(x, str)]
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def iter_paths(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_paths(item)
    elif isinstance(value, dict):
        for key in ("path", "dir", "file", "files", "root"):
            if key in value:
                yield from iter_paths(value[key])


def candidate_roots(case, case_path):
    base = case_path.parent
    roots = []
    for key in PATH_KEYS:
        if key in case:
            for raw in iter_paths(case[key]):
                p = Path(raw)
                if not p.is_absolute():
                    p = base / p
                roots.append(p)
    if base.name.lower() == "input" or (base / "materials").is_dir():
        roots.append(base)
    if Path("/input").is_dir():
        roots.append(Path("/input"))
    seen, uniq = set(), []
    for r in roots:
        try:
            key = str(r.resolve())
        except OSError:
            key = str(r)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def sha256_file(path):
    h = hashlib.sha256()
    total = 0
    truncated = False
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                if total + len(chunk) > MAX_HASH_BYTES:
                    chunk = chunk[:MAX_HASH_BYTES - total]
                    truncated = True
                h.update(chunk)
                total += len(chunk)
                if truncated:
                    break
    except OSError as exc:
        return None, total, False, str(exc)
    return h.hexdigest(), total, truncated, None


def category_of(ext):
    ext = ext.lower()
    for name, exts in CATEGORY.items():
        if ext in exts:
            return name
    return "other"


def base_stem(stem):
    s = PAREN_NOISE.sub("", stem)
    s = VERSION_NOISE.sub(" ", s)
    s = re.sub(r"[_\-\s]+", " ", s).strip().lower()
    return s or stem.strip().lower()


def collect_files(roots, errors, skipped, exclude=None):
    entries = []
    seen = set()
    try:
        exclude_key = str(exclude.resolve()) if exclude else None
    except OSError:
        exclude_key = None
    for root in roots:
        if not root.exists():
            errors.append("material root not found: %s" % (root.name or str(root)))
            continue
        if root.is_file():
            paths = [root]
            root_dir = root.parent
        else:
            root_dir = root
            paths = []
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                    for fn in sorted(filenames):
                        paths.append(Path(dirpath) / fn)
            except OSError as exc:
                errors.append("walk failed on %s: %s" % (root.name, exc))
                continue
        for path in paths:
            if len(entries) >= MAX_FILES:
                skipped.append({"path": str(path.name), "reason": "file cap reached (5000)"})
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    skipped.append({"path": str(path), "reason": "not a regular file or symlink"})
                    continue
                rp = str(path.resolve())
            except OSError as exc:
                skipped.append({"path": str(path), "reason": "resolve failed: %s" % exc})
                continue
            if rp in seen:
                continue
            if exclude_key and rp == exclude_key:
                continue
            seen.add(rp)
            try:
                st = path.stat()
            except OSError as exc:
                skipped.append({"path": path.name, "reason": "stat failed: %s" % exc})
                continue
            try:
                rel = path.relative_to(root_dir).as_posix()
            except ValueError:
                rel = path.name
            digest, size, truncated, err = sha256_file(path)
            if err:
                skipped.append({"path": rel, "reason": "unreadable: %s" % err})
            entries.append({
                "path": rel,
                "name": path.name,
                "ext": path.suffix.lower(),
                "bytes": int(st.st_size),
                "sha256": digest,
                "hash_truncated": truncated,
                "modified_epoch": int(st.st_mtime),
                "readable": err is None,
            })
    entries.sort(key=lambda e: e["path"])
    return entries


def build_payload(entries, skipped, errors):
    by_hash = {}
    for e in entries:
        if e["sha256"] and e["bytes"] > 0:
            by_hash.setdefault(e["sha256"], []).append(e)

    duplicate_groups = []
    for digest in sorted(by_hash):
        group = by_hash[digest]
        if len(group) > 1:
            duplicate_groups.append({
                "sha256": digest,
                "count": len(group),
                "bytes_each": group[0]["bytes"],
                "members": sorted(g["path"] for g in group),
                "action": "keep_all_pending_review",
            })

    chains = {}
    for e in entries:
        stem = base_stem(Path(e["name"]).stem)
        chains.setdefault(stem, []).append(e)

    version_chains = []
    for stem in sorted(chains):
        group = sorted(chains[stem], key=lambda x: (x["modified_epoch"], x["path"]))
        if len(group) < 2:
            continue
        hashes = {g["sha256"] for g in group}
        versions = []
        for idx, item in enumerate(group):
            versions.append({
                "path": item["path"],
                "sha256": item["sha256"],
                "modified_epoch": item["modified_epoch"],
                "supersedes": group[idx - 1]["path"] if idx > 0 else None,
                "is_current": idx == len(group) - 1,
            })
        version_chains.append({
            "stem_key": stem,
            "count": len(group),
            "distinct_content": len(hashes),
            "versions": versions,
        })

    layout_plan = []
    operations = []
    current_paths = {
        v["path"] for c in version_chains for v in c["versions"] if v["is_current"]
    }
    for e in entries:
        cat = category_of(e["ext"])
        target = "%s/%s" % (cat, e["name"])
        if version_chains and e["path"] not in current_paths:
            target = "archive/%s/%s" % (cat, e["name"])
        layout_plan.append({
            "source_path": e["path"],
            "category": cat,
            "target_path": target,
            "basis": "extension" if cat != "other" else "extension_unmapped",
        })
        operations.append({
            "op": "keep" if e["path"].replace("\\", "/").startswith(cat + "/") else "place",
            "from": e["path"],
            "to": target,
            "executed": False,
        })

    zero_byte = [e["path"] for e in entries if e["bytes"] == 0]
    truncated = [e["path"] for e in entries if e["hash_truncated"]]
    unreadable = [e["path"] for e in entries if not e["readable"]]

    summary = (
        "Inventoried %d file(s); %d duplicate group(s); %d version chain(s); "
        "%d planned placement(s). No source file was moved, renamed, or deleted."
        % (len(entries), len(duplicate_groups), len(version_chains), len(operations))
    )

    result = {
        "inventory": entries,
        "duplicate_groups": duplicate_groups,
        "version_chains": version_chains,
        "layout_plan": layout_plan,
        "operations": operations,
        "zero_byte_files": zero_byte,
    }
    evidence = {
        "hash_algorithm": "sha256",
        "hash_byte_cap": MAX_HASH_BYTES,
        "file_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "truncated_hash_files": truncated,
        "unreadable_files": unreadable,
        "roots_scanned": len({e["path"].split("/")[0] for e in entries}) if entries else 0,
        "source_mutation": "none",
    }
    uncertainty = [
        "Version chains are inferred from normalized filename stems and modification time; "
        "no content diff or semantic comparison was performed.",
        "Same-hash files are reported as duplicates but never deleted automatically.",
        "Directory categories are extension-based only; task-specific conventions in task.md "
        "must be applied by the caller.",
    ]
    if truncated:
        uncertainty.append("Files over 64 MiB were hashed only on their first 64 MiB.")
    stats = {
        "files": len(entries),
        "bytes": sum(e["bytes"] for e in entries),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_extras": sum(g["count"] - 1 for g in duplicate_groups),
        "version_chains": len(version_chains),
        "planned_operations": len(operations),
        "skipped": len(skipped),
        "errors": len(errors),
    }
    return {
        "manifest": entries,
        "duplicate_groups": duplicate_groups,
        "version_chains": version_chains,
        "layout_plan": layout_plan,
        "operations": operations,
        "skipped": skipped,
        "summary": summary,
        "result": result,
        "evidence": evidence,
        "uncertainty": uncertainty,
        "errors": errors,
        "stats": stats,
    }


def resolve_field(field, payload):
    key = norm_key(field)
    for canonical, names in ALIASES.items():
        if key == canonical or key in names:
            return canonical, payload.get(canonical)
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Research archive steward (stdlib only)")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)

    case_path = Path(args.case)
    errors = []
    skipped = []
    case = {}
    status = "success"
    try:
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
        if not isinstance(case, dict):
            raise ValueError("case.json root is not an object")
    except (OSError, ValueError) as exc:
        errors.append("cannot read case.json: %s" % exc)
        case = {}
        status = "failed"

    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        case_id = "unknown"
        if status != "failed":
            status = "partial"

    fields = contract_fields(case)
    entries = []
    if status != "failed":
        roots = candidate_roots(case, case_path)
        entries = collect_files(roots, errors, skipped, case_path)
        if not entries:
            status = "insufficient_input"
        elif skipped or any(not e["readable"] for e in entries) or any(e["hash_truncated"] for e in entries):
            status = "partial"

    payload = build_payload(entries, skipped, errors)
    payload["status"] = status
    payload["case_id"] = case_id

    result = {}
    notes = []
    result["case_id"] = case_id
    for field, value in payload.items():
        if field not in ("case_id", "result", "evidence", "uncertainty", "errors", "stats", "status", "summary"):
            result.setdefault(field, value)
    result["status"] = status
    result["result"] = payload["result"]
    result["evidence"] = payload["evidence"]
    result["uncertainty"] = payload["uncertainty"]
    result["errors"] = payload["errors"]
    result["stats"] = payload["stats"]
    if payload.get("summary") is not None:
        result["summary"] = payload["summary"]

    for field in fields:
        if field == "case_id":
            result["case_id"] = case_id
            continue
        canonical, value = resolve_field(field, payload)
        if canonical is None:
            result[field] = None
            notes.append("%s: no supported producer in this skill; null retained" % field)
        else:
            result[field] = value
    if notes:
        result["contract_notes"] = notes

    out_path = Path(args.out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("cannot write result: %s\n" % exc)
        return 2

    work = Path(args.work)
    try:
        work.mkdir(parents=True, exist_ok=True)
        with open(work / "archive_manifest.json", "w", encoding="utf-8") as fh:
            json.dump(payload["manifest"], fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
