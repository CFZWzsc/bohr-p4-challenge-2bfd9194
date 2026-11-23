#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic research-library ingest steward.

Standard library only. No network. Never deletes or overwrites source files.

Dry-run mode (default) scans the input tree, hashes every readable file,
infers metadata, detects duplicates and version chains, and writes a full
plan plus /app/output/result.json. Apply mode (--apply) copies planned files
into /app/output/library without ever overwriting an existing target.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

VERSION = "1.0.0"

TEXT_EXTS = {".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".jsonl",
             ".yaml", ".yml", ".xml", ".r", ".py", ".sh", ".bib"}
META_FIELDS = ("title", "authors", "year", "journal", "doi", "project", "instrument")

ROOT_KEYS = (
    "input_dir", "input_root", "materials_dir", "materials", "data_dir",
    "dataset_dir", "corpus_dir", "library_dir", "files_dir", "directory",
    "path", "root", "source_dir",
)

DEFAULT_POLICY = {
    "schema_version": "1.0",
    "hash": {"algorithm": "sha256", "chunk_bytes": 1048576, "max_hash_bytes": 67108864},
    "caps": {"max_files": 5000, "max_depth": 32, "max_name_chars": 120, "max_path_chars": 240},
    "naming": {
        "unicode_form": "NFC",
        "forbidden_chars": "<>:\"/\\|?*#%",
        "replacement": "_",
        "whitespace": "_",
        "collapse_repeats": True,
        "lowercase_extension": True,
        "max_stem_chars": 120,
        "reserved_names": ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3",
                           "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                           "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6",
                           "LPT7", "LPT8", "LPT9"],
        "template": "{project}/{category}/{filename}",
        "archive_template": "{project}/_archive/{category}/{filename}",
        "sidecar_template": "{project}/_metadata/{filename}",
        "fallbacks": {"project": "_unassigned", "year": "nd", "category": "other"},
    },
    "categories": {
        "documents": [".pdf", ".doc", ".docx", ".md", ".txt", ".tex", ".rtf",
                      ".odt", ".pptx", ".ppt", ".epub", ".bib"],
        "data": [".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl", ".sqlite",
                 ".db", ".h5", ".hdf5", ".parquet", ".xml", ".yaml", ".yml",
                 ".dat", ".bin"],
        "images": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".svg",
                   ".gif", ".webp"],
        "archives": [".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2"],
        "code": [".py", ".r", ".m", ".sh", ".ipynb", ".jl", ".cpp", ".c", ".h", ".java"],
        "other": [],
    },
    "exclude_dirs": [".git", "__pycache__", "node_modules", ".venv", "venv",
                     ".cache", ".idea", ".vscode", "$RECYCLE.BIN"],
    "sidecar": {"suffixes": [".meta.json", ".metadata.json"],
                "global_files": ["metadata.json", "metadata.csv"]},
    "safety": {"allow_move": False, "allow_delete": False, "overwrite": "never"},
    "apply": {"library_subdir": "library", "copy_preserve_times": True,
              "verify_sha256_after_copy": True},
    "required_metadata": ["title", "authors", "year"],
    "write_review": True,
}

# Contract key aliases. First registration wins; the order below is the
# documented priority. Chinese aliases are kept because cases are written in
# Chinese.
ALIAS = {}


def _reg(canon, names):
    for name in names:
        ALIAS.setdefault(norm_key(name), canon)


def build_aliases():
    _reg("case_id", ["case_id", "caseid", "id", "案例id", "案例编号"])
    _reg("inventory", ["files", "file", "file_list", "filelist", "items", "item",
                       "records", "record", "inventory", "inventories", "listing",
                       "index", "file_index", "catalog", "state", "states",
                       "文件", "文件清单", "文件列表"])
    _reg("manifest", ["manifest", "manifests", "file_manifest", "moves", "move",
                      "renames", "rename", "operations", "operation", "plan",
                      "placement", "placements", "files_organized", "操作",
                      "操作清单", "移动", "入库清单"])
    _reg("duplicates", ["duplicates", "duplicate", "dupes", "dup",
                        "duplicate_files", "duplicate_groups", "dedup",
                        "重复", "重复文件"])
    _reg("versions", ["versions", "version", "version_chains", "version_chain",
                      "version_relations", "version_groups", "revisions",
                      "revision_chain", "版本", "版本链", "版本关系"])
    _reg("conflicts", ["conflicts", "conflict", "collisions", "collision",
                       "target_conflicts", "冲突"])
    _reg("skipped", ["skipped", "skip", "skips", "excluded", "unreadable",
                     "unprocessed", "failed_files", "ignored", "跳过",
                     "跳过文件", "未处理"])
    _reg("summary", ["summary", "report", "overview", "answer", "conclusion",
                     "notes", "description", "abstract", "报告", "摘要", "结论"])
    _reg("evidence", ["evidence", "proof", "verification", "checks", "证据", "校验"])
    _reg("sources", ["source", "sources", "provenance", "origins", "来源"])
    _reg("status", ["status", "run_status", "outcome", "状态"])
    _reg("mode", ["mode", "run_mode", "运行模式"])
    _reg("applied", ["applied", "apply", "executed", "是否执行"])
    _reg("dry_run", ["dry_run", "dryrun", "是否试运行"])
    _reg("errors", ["errors", "error", "issues", "问题", "错误"])
    _reg("uncertainty", ["uncertainty", "uncertainties", "limitations",
                         "warnings", "不确定", "限制"])
    _reg("rollback_plan", ["rollback", "rollback_plan", "undo", "restore", "回滚"])
    _reg("logs", ["logs", "log", "run_log", "audit", "change_log", "日志"])
    _reg("unresolved_metadata", ["unresolved_metadata", "unresolved",
                                 "missing_metadata", "未解析", "元数据缺失"])
    _reg("plan_actions", ["plan_actions", "actions", "action_plan", "计划",
                          "操作计划"])
    _reg("renamed", ["renamed", "renames", "renamed_files", "重命名"])
    _reg("metadata", ["metadata", "meta", "metadata_table", "fields", "元数据"])
    _reg("layout", ["layout", "layout_plan", "directory_tree", "tree",
                    "structure", "target_layout", "目录", "目录树"])
    _reg("hashes", ["hashes", "hash", "sha256", "checksums", "checksum", "哈希"])
    _reg("stats", ["stats", "statistics", "counts", "统计"])
    _reg("result", ["result", "results", "data", "结果"])
    _reg("selfcheck", ["selfcheck", "self_check", "自检"])


def norm_key(name):
    """Normalize a contract key for alias lookup; keep CJK characters."""
    s = str(name).strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", s)
    return s.strip("_").lower()


def load_json_file(path):
    try:
        with open(str(path), "r", encoding="utf-8-sig") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "not_found: %s" % Path(path).name
    except (OSError, ValueError) as exc:
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:240])


def deep_merge(base, extra):
    if not isinstance(extra, dict):
        return base
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_policy(explicit):
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / "policy.json")
    for candidate in candidates:
        if candidate and candidate.is_file():
            obj, err = load_json_file(candidate)
            if err:
                return policy, "policy %s: %s" % (candidate.name, err)
            if isinstance(obj, dict):
                deep_merge(policy, obj)
            return policy, None
    return policy, None


def apply_case_policy(policy, case):
    """Translate optional per-case policy blocks into the policy structure."""
    if not isinstance(case, dict):
        return
    for section in ("naming", "caps", "hash", "apply", "safety", "sidecar",
                    "categories", "exclude_dirs", "write_review"):
        if isinstance(case.get(section), dict) or section == "exclude_dirs":
            if section == "exclude_dirs" and isinstance(case.get(section), list):
                policy[section] = case[section]
            elif isinstance(case.get(section), dict):
                deep_merge(policy[section], case[section])
    if isinstance(case.get("target_template"), str):
        policy["naming"]["template"] = case["target_template"]
    if isinstance(case.get("archive_template"), str):
        policy["naming"]["archive_template"] = case["archive_template"]
    cp = case.get("policy")
    if isinstance(cp, dict):
        naming = policy["naming"]
        if isinstance(cp.get("target_template"), str):
            naming["template"] = cp["target_template"]
        if isinstance(cp.get("archive_template"), str):
            naming["archive_template"] = cp["archive_template"]
        if isinstance(cp.get("sidecar_template"), str):
            naming["sidecar_template"] = cp["sidecar_template"]
        if isinstance(cp.get("project_placeholder"), str):
            naming.setdefault("fallbacks", {})["project"] = cp["project_placeholder"]
        for section in ("naming", "caps", "hash", "apply", "safety", "categories"):
            if isinstance(cp.get(section), dict):
                deep_merge(policy[section], cp[section])
        if isinstance(cp.get("max_hash_bytes"), int) and cp["max_hash_bytes"] > 0:
            policy["hash"]["max_hash_bytes"] = cp["max_hash_bytes"]
        if isinstance(cp.get("allow_move"), bool):
            policy["safety"]["allow_move"] = cp["allow_move"]
        if isinstance(cp.get("library_subdir"), str):
            policy["apply"]["library_subdir"] = cp["library_subdir"]
    req = case.get("required_metadata")
    if isinstance(req, list) and all(isinstance(x, str) for x in req):
        policy["required_metadata"] = [x for x in req if x in META_FIELDS]


def extract_contract_keys(case):
    oc = None
    for name in ("output_contract", "output_schema", "contract"):
        if isinstance(case, dict) and case.get(name) is not None:
            oc = case[name]
            break
    keys = []
    meta_keys = {"type", "description", "title", "$schema", "additionalProperties",
                 "required", "properties", "fields", "outputs", "items"}

    def add(value):
        if isinstance(value, str) and value.strip():
            keys.append(value.strip())
        elif isinstance(value, dict):
            for nk in ("name", "field", "key", "id"):
                if isinstance(value.get(nk), str):
                    keys.append(value[nk].strip())
                    break

    if isinstance(oc, dict):
        props = oc.get("properties")
        if isinstance(props, dict):
            keys.extend([str(k) for k in props.keys()])
        elif isinstance(props, list):
            for item in props:
                add(item)
        for field_name in ("fields", "outputs", "items"):
            block = oc.get(field_name)
            if isinstance(block, dict):
                keys.extend([str(k) for k in block.keys()])
            elif isinstance(block, list):
                for item in block:
                    add(item)
        required = oc.get("required")
        if isinstance(required, list):
            keys.extend([x for x in required if isinstance(x, str)])
        if not keys:
            keys.extend([str(k) for k in oc.keys() if k not in meta_keys
                         and not str(k).startswith("$")])
    elif isinstance(oc, list):
        for item in oc:
            add(item)
    elif isinstance(oc, str):
        keys.extend([x for x in re.split(r"[,;\s]+", oc) if x])

    seen, out = set(), []
    for key in keys:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, dict):
        for key in ("path", "dir", "file", "files", "root"):
            if key in value:
                yield from iter_strings(value[key])


def resolve_roots(case, input_dir):
    roots = []
    for key in ROOT_KEYS:
        if isinstance(case, dict) and key in case:
            for raw in iter_strings(case[key]):
                p = Path(raw)
                if not p.is_absolute():
                    p = input_dir / p
                roots.append(p)
    if not roots:
        candidate = input_dir / "materials"
        roots.append(candidate if candidate.is_dir() else input_dir)
    seen, out = set(), []
    for root in roots:
        key = safe_resolve(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def safe_resolve(path):
    try:
        return str(Path(path).resolve(strict=False))
    except (OSError, RuntimeError):
        return os.path.abspath(str(path))


def posix_rel(path, root):
    try:
        rel = Path(path).relative_to(root).as_posix()
        return rel if rel and rel != "." else Path(path).name
    except ValueError:
        try:
            rel = os.path.relpath(str(path), str(root))
            return Path(rel).as_posix()
        except (OSError, ValueError):
            return Path(path).name


def posix_parent(rel):
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def hash_file(path, cap):
    digest = hashlib.sha256()
    total = 0
    try:
        with open(str(path), "rb") as fh:
            while total < cap:
                chunk = fh.read(min(1048576, cap - total))
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        return None, total, False, str(exc)[:300]
    return digest.hexdigest(), total, False, None


def category_of(ext, policy):
    ext = (ext or "").lower()
    categories = policy.get("categories", {})
    for name in sorted(categories):
        if name == "other":
            continue
        if ext in [x.lower() for x in categories.get(name, [])]:
            return name
    return "other"


def sanitize_component(text, naming):
    form = naming.get("unicode_form", "NFC")
    s = unicodedata.normalize(form, str(text))
    forbidden = set(naming.get("forbidden_chars", "<>:\"/\\|?*#%"))
    replacement = naming.get("replacement", "_")
    out = []
    for ch in s:
        if ord(ch) < 32 or ch in forbidden:
            out.append(replacement)
        else:
            out.append(ch)
    s = "".join(out)
    ws = naming.get("whitespace", "_")
    s = re.sub(r"\s+", ws, s)
    if naming.get("collapse_repeats", True) and replacement:
        s = re.sub(re.escape(replacement) + r"{2,}", replacement, s)
    s = s.strip(" .-")
    return s or "_unnamed"


def split_name(name):
    suffix = Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    return stem, suffix


def sanitize_filename(name, naming):
    stem, suffix = split_name(name)
    reasons = []
    if unicodedata.normalize(naming.get("unicode_form", "NFC"), name) != name:
        reasons.append("unicode_nfc")
    if re.search(r"\s", stem):
        reasons.append("whitespace_normalized")
    forbidden = set(naming.get("forbidden_chars", ""))
    if any(ch in forbidden for ch in stem):
        reasons.append("illegal_char_replaced")
    new_stem = sanitize_component(stem, naming)
    limit = int(naming.get("max_stem_chars", 120))
    if len(new_stem) > limit:
        new_stem = new_stem[:limit].rstrip(" .-")
        reasons.append("length_capped")
    if new_stem.upper() in [x.upper() for x in naming.get("reserved_names", [])]:
        new_stem = "_" + new_stem
        reasons.append("reserved_name_escaped")
    if suffix and naming.get("lowercase_extension", True) and suffix != suffix.lower():
        suffix = suffix.lower()
        reasons.append("extension_lowercased")
    return new_stem + suffix, reasons


MARKER_TOKENS = {
    "final": 1000, "定稿": 1000, "最终": 1000,
    "new": 500, "新版": 500,
    "draft": -100, "初稿": -100,
    "old": -50, "旧版": -50, "backup": -50, "备份": -50,
    "修订": 20,
}


def normalize_stem(stem):
    """Return (group key, marker info). Only explicit revision markers are removed."""
    s = unicodedata.normalize("NFC", stem)
    s = re.sub(r"\(\s*(\d+)\s*\)", r" __paren\1__ ", s)
    tokens = [t for t in re.split(r"[._\-\s]+", s) if t]
    kept, markers, ranks = [], [], []
    for token in tokens:
        low = token.lower()
        paren = re.match(r"^__paren(\d+)__$", token)
        vmark = re.match(r"^(v|ver|version|rev|r)(\d+(?:\.\d+)*)?$", low)
        copymark = re.match(r"^(copy|副本)(\d*)$", low)
        version_cn = re.match(r"^版本(\d*)$", token)
        if paren:
            rank = 10 + int(paren.group(1))
            markers.append(token)
            ranks.append(rank)
        elif low in MARKER_TOKENS:
            markers.append(token)
            ranks.append(MARKER_TOKENS[low])
        elif vmark:
            try:
                rank = int(float(vmark.group(2))) if vmark.group(2) else 1
            except ValueError:
                rank = 1
            markers.append(token)
            ranks.append(rank)
        elif copymark:
            rank = 10 + (int(copymark.group(2)) if copymark.group(2) else 1)
            markers.append(token)
            ranks.append(rank)
        elif version_cn:
            rank = int(version_cn.group(1)) if version_cn.group(1) else 1
            markers.append(token)
            ranks.append(rank)
        else:
            kept.append(low)
    key = " ".join(kept).strip()
    if not key:
        key = "_unnamed"
    return key, {
        "has_marker": bool(markers),
        "marker": " ".join(markers),
        "rank": max(ranks) if ranks else 0,
    }


def scan_materials(roots, policy, exclude_keys, logs, skipped, errors):
    inventory = []
    caps = policy.get("caps", {})
    max_files = int(caps.get("max_files", 5000))
    max_depth = int(caps.get("max_depth", 32))
    hash_cfg = policy.get("hash", {})
    cap = int(hash_cfg.get("max_hash_bytes", 67108864))
    exclude_dirs = set(policy.get("exclude_dirs", []))
    seen = set()

    def add_skip(kind, path, reason, error=None):
        rec = {"kind": kind, "path": path, "reason": reason}
        if error:
            rec["error"] = str(error)[:300]
        skipped.append(rec)

    def add_file(path, root, depth):
        if len(inventory) >= max_files:
            add_skip("file", posix_rel(path, root), "file_cap_reached")
            return
        key = safe_resolve(path)
        if key in seen:
            return
        if key in exclude_keys:
            return
        try:
            st = os.stat(str(path), follow_symlinks=False)
        except OSError as exc:
            add_skip("entry", posix_rel(path, root), "stat_failed", exc)
            return
        if not os.path.isfile(str(path)):
            add_skip("special_file", posix_rel(path, root), "not_a_regular_file")
            return
        seen.add(key)
        digest, _, _, err = hash_file(path, cap)
        truncated = bool(st.st_size > cap)
        rel = posix_rel(path, root)
        entry = {
            "path": rel,
            "name": path.name,
            "ext": (path.suffix or "").lower(),
            "category": category_of(path.suffix, policy),
            "role": "material",
            "bytes": int(st.st_size),
            "sha256": digest,
            "hash_algorithm": hash_cfg.get("algorithm", "sha256"),
            "hash_truncated": truncated,
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            "mtime_epoch": int(st.st_mtime),
            "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            "depth": depth,
            "readable": err is None,
            "symlink": False,
            "_abs": str(path),
        }
        if err:
            add_skip("file", rel, "unreadable", err)
        inventory.append(entry)

    for root in roots:
        if not root.exists():
            add_skip("directory", str(root), "root_not_found")
            continue
        if root.is_file():
            add_file(root, root.parent, 0)
            continue
        stack = [(root, 0)]
        while stack:
            dirpath, depth = stack.pop()
            try:
                with os.scandir(str(dirpath)) as handle:
                    entries = sorted(list(handle), key=lambda e: e.name)
            except OSError as exc:
                add_skip("directory", posix_rel(dirpath, root), "unreadable_directory", exc)
                continue
            if not entries and depth > 0:
                add_skip("directory", posix_rel(dirpath, root), "empty_directory")
            child_dirs = []
            for entry in entries:
                try:
                    is_link = entry.is_symlink()
                except OSError:
                    is_link = False
                rel = posix_rel(Path(entry.path), root)
                if is_link:
                    add_skip("symlink", rel, "symlink_not_followed")
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in exclude_dirs:
                            add_skip("directory", rel, "excluded_by_policy")
                        elif depth + 1 > max_depth:
                            add_skip("directory", rel, "depth_cap")
                        else:
                            child_dirs.append((Path(entry.path), depth + 1))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        add_skip("special_file", rel, "not_a_regular_file")
                        continue
                except OSError as exc:
                    add_skip("entry", rel, "stat_failed", exc)
                    continue
                add_file(Path(entry.path), root, depth)
            stack.extend(reversed(child_dirs))
    inventory.sort(key=lambda item: item["path"])
    return inventory


def _norm_authors(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[;；]", value) if p.strip()]
        return parts or [value.strip()]
    return None


def _norm_year(value):
    if isinstance(value, int) and 1000 <= value <= 2999:
        return value
    if isinstance(value, str):
        match = re.search(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", value)
        if match:
            return int(match.group(1))
    return None


def _probe_text(path, limit=16384):
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def collect_sidecars(inventory, roots, policy, skipped):
    """Attach per-file sidecars and optional global metadata tables."""
    sidecars = {}
    global_map = {}
    by_path = {e["path"]: e for e in inventory}
    suffixes = policy.get("sidecar", {}).get("suffixes", [".meta.json", ".metadata.json"])
    skip_seen = set()

    def add_skip(kind, path, reason, error=None):
        key = (kind, path, reason)
        if key in skip_seen:
            return
        skip_seen.add(key)
        rec = {"kind": kind, "path": path, "reason": reason}
        if error:
            rec["error"] = str(error)[:300]
        skipped.append(rec)

    for entry in inventory:
        name = entry["name"]
        matched_suffix = None
        for suffix in suffixes:
            if name.endswith(suffix):
                matched_suffix = suffix
                break
        if not matched_suffix:
            continue
        entry["role"] = "sidecar"
        base = name[:-len(matched_suffix)]
        parent = posix_parent(entry["path"])
        target_rel = (parent + "/" + base) if parent else base
        target = by_path.get(target_rel)
        data, err = load_json_file(entry["_abs"])
        if err:
            add_skip("sidecar", entry["path"], "invalid_sidecar_json", err)
        if target is None:
            add_skip("sidecar", entry["path"], "orphan_sidecar")
            continue
        if isinstance(data, dict):
            sidecars[target["path"]] = data

    global_files = policy.get("sidecar", {}).get("global_files", [])
    for root in roots:
        if not root.is_dir():
            continue
        for gf in global_files:
            path = root / gf
            if not path.is_file():
                continue
            for entry in inventory:
                if safe_resolve(entry["_abs"]) == safe_resolve(path):
                    entry["role"] = "sidecar"
            if gf.lower().endswith(".json"):
                data, err = load_json_file(path)
                if err:
                    add_skip("sidecar", gf, "invalid_global_metadata", err)
                    continue
                table = data.get("files") if isinstance(data, dict) and isinstance(data.get("files"), dict) else data
                if isinstance(table, dict):
                    for key, value in table.items():
                        if isinstance(value, dict):
                            global_map[str(key)] = value
            elif gf.lower().endswith(".csv"):
                try:
                    with open(str(path), "r", encoding="utf-8-sig", newline="") as fh:
                        reader = csv.DictReader(fh)
                        for row in reader:
                            key = row.get("path") or row.get("file") or row.get("filename")
                            if key:
                                global_map[str(key)] = dict(row)
                except (OSError, csv.Error) as exc:
                    add_skip("sidecar", gf, "invalid_global_metadata_csv", exc)
    return sidecars, global_map


def case_metadata(case):
    meta = {}
    block = case.get("metadata") if isinstance(case, dict) else None
    if isinstance(block, dict):
        meta.update(block)
    for field in META_FIELDS:
        if isinstance(case, dict) and case.get(field) not in (None, ""):
            meta[field] = case[field]
    meta["_apply_all"] = bool(meta.get("apply_to_all"))
    return meta


def _put(fields, name, value, source, confidence):
    if value in (None, "", [], {}):
        fields[name] = {"value": None, "source": None, "confidence": 0.0}
    else:
        fields[name] = {"value": value, "source": source, "confidence": confidence}


def infer_metadata(entry, sidecar, global_map, case_meta, policy):
    fields = {}
    name = entry["name"]
    stem = Path(name).stem
    side = sidecar or global_map.get(entry["path"]) or global_map.get(name) or {}
    text = _probe_text(entry["_abs"]) if entry["ext"] in TEXT_EXTS else ""

    heading = None
    if entry["ext"] in (".md", ".txt", ".tex", ".rtf", ".odt"):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#"):
                heading = re.sub(r"^#+\s*", "", line).strip()
                if heading:
                    break
            elif line:
                heading = line[:200]
                break

    clean_stem = normalize_stem(stem)[0].replace("_", " ").strip()
    title_value = side.get("title") or side.get("name")
    if title_value:
        _put(fields, "title", str(title_value).strip(), "sidecar", 1.0)
    elif heading:
        _put(fields, "title", heading, "content", 0.6)
    elif clean_stem:
        _put(fields, "title", clean_stem, "filename", 0.45)
    else:
        _put(fields, "title", None, None, 0.0)

    authors = _norm_authors(side.get("authors") or side.get("author"))
    if authors:
        _put(fields, "authors", authors, "sidecar", 1.0)
    elif case_meta.get("_apply_all") and case_meta.get("authors"):
        _put(fields, "authors", _norm_authors(case_meta["authors"]), "case_json", 0.7)
    else:
        _put(fields, "authors", None, None, 0.0)

    year = _norm_year(side.get("year"))
    if year:
        _put(fields, "year", year, "sidecar", 1.0)
    else:
        match = re.search(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", stem)
        if match:
            _put(fields, "year", int(match.group(1)), "filename", 0.6)
        else:
            match = re.search(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", text)
            if match:
                _put(fields, "year", int(match.group(1)), "content", 0.45)
            elif case_meta.get("_apply_all") and case_meta.get("year"):
                _put(fields, "year", _norm_year(case_meta["year"]), "case_json", 0.7)
            else:
                _put(fields, "year", None, None, 0.0)

    journal = side.get("journal") or side.get("venue")
    if journal:
        _put(fields, "journal", str(journal).strip(), "sidecar", 1.0)
    elif case_meta.get("_apply_all") and case_meta.get("journal"):
        _put(fields, "journal", str(case_meta["journal"]).strip(), "case_json", 0.7)
    else:
        _put(fields, "journal", None, None, 0.0)

    doi_text = " ".join([str(side.get("doi") or ""), stem, text[:4000]])
    doi_match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", doi_text)
    if side.get("doi"):
        _put(fields, "doi", str(side["doi"]).strip(), "sidecar", 1.0)
    elif doi_match:
        doi = doi_match.group(0).rstrip(".,;)")
        source = "filename" if doi in stem else "content"
        _put(fields, "doi", doi, source, 0.6 if source == "filename" else 0.5)
    else:
        _put(fields, "doi", None, None, 0.0)

    project = side.get("project") or side.get("project_id")
    if project:
        _put(fields, "project", str(project).strip(), "sidecar", 1.0)
    elif case_meta.get("project"):
        _put(fields, "project", str(case_meta["project"]).strip(), "case_json", 0.8)
    else:
        _put(fields, "project", None, None, 0.0)

    instrument = side.get("instrument") or side.get("instrument_model")
    if instrument:
        _put(fields, "instrument", str(instrument).strip(), "sidecar", 1.0)
    elif case_meta.get("instrument"):
        _put(fields, "instrument", str(case_meta["instrument"]).strip(), "case_json", 0.8)
    else:
        _put(fields, "instrument", None, None, 0.0)
    return fields


def build_metadata(inventory, sidecars, global_map, case_meta, policy, skipped):
    required = [x for x in policy.get("required_metadata", []) if x in META_FIELDS]
    records, by_path, unresolved = [], {}, []
    for entry in inventory:
        fields = infer_metadata(entry, sidecars.get(entry["path"]), global_map, case_meta, policy)
        record = {"path": entry["path"], "sha256": entry["sha256"], "fields": fields}
        records.append(record)
        by_path[entry["path"]] = fields
        if entry["role"] == "sidecar" or not entry["readable"]:
            continue
        missing = [name for name in required if fields.get(name, {}).get("value") is None]
        if missing:
            unresolved.append({"path": entry["path"], "missing_fields": missing,
                               "source_boundary": "no sidecar value; not guessed"})
            record["unresolved"] = missing
    return records, by_path, unresolved


def check_declared(case, input_dir, inventory, skipped):
    declared = None
    if isinstance(case, dict):
        for key in ("declared_files", "expected_files", "files_expected"):
            if isinstance(case.get(key), list):
                declared = case[key]
                break
    if not declared:
        return
    inv_paths = {e["path"] for e in inventory}
    for raw in declared:
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = input_dir / path
        display = raw.replace("\\", "/")
        if not path.exists():
            skipped.append({"kind": "declared_file", "path": display,
                            "reason": "declared_but_missing"})
        elif path.is_dir():
            skipped.append({"kind": "declared_file", "path": display,
                            "reason": "declared_path_is_not_regular_file"})
        elif path.is_file():
            rel = None
            for root in (input_dir,):
                try:
                    rel = path.relative_to(root).as_posix()
                    break
                except ValueError:
                    continue
            if rel and rel not in inv_paths:
                skipped.append({"kind": "declared_file", "path": display,
                                "reason": "present_but_outside_material_roots"})


def build_duplicates(inventory):
    by_key, zero = {}, []
    for entry in inventory:
        if not entry["readable"] or not entry["sha256"]:
            continue
        if entry["bytes"] == 0:
            zero.append(entry["path"])
            continue
        # Size is part of the key: a truncated prefix hash must not join two
        # different large files whose tails differ.
        by_key.setdefault((entry["sha256"], entry["bytes"]), []).append(entry)
    groups = []
    for digest, size in sorted(by_key):
        members = sorted(by_key[(digest, size)], key=lambda x: x["path"])
        if len(members) < 2:
            continue
        groups.append({
            "sha256": digest,
            "count": len(members),
            "extra_copies": len(members) - 1,
            "bytes_each": members[0]["bytes"],
            "reclaimable_bytes": members[0]["bytes"] * (len(members) - 1),
            "members": [m["path"] for m in members],
            "canonical": members[0]["path"],
            "basis": "sha256_content",
            "hash_truncated": any(m["hash_truncated"] for m in members),
            "action": "keep_all_no_delete",
        })
    return groups, zero


def build_versions(inventory, conflicts):
    groups = {}
    for entry in inventory:
        if not entry["readable"] or not entry["sha256"] or entry["role"] == "sidecar":
            continue
        stem = Path(entry["name"]).stem
        key, info = normalize_stem(stem)
        entry["_stem_key"] = key
        entry["_marker_info"] = info
        groups.setdefault((key, entry["ext"].lower()), []).append(entry)
    chains = []
    for (key, ext), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        hashes = {m["sha256"] for m in members}
        if len(hashes) < 2:
            continue
        parents = {posix_parent(m["path"]) for m in members}
        any_marker = any(m["_marker_info"]["has_marker"] for m in members)
        same_parent = len(parents) == 1
        if not any_marker and not same_parent:
            conflicts.append({
                "type": "stem_ambiguity",
                "stem_key": key,
                "extension": ext,
                "members": sorted(m["path"] for m in members),
                "resolution": "kept_separate_disambiguated_targets",
                "note": "No revision marker and different directories; not treated as a version chain.",
            })
            continue
        ordered = sorted(members, key=lambda x: (x["mtime_ns"], x["_marker_info"]["rank"], x["path"]))
        chain_id = "VC%03d" % (len(chains) + 1)
        versions = []
        for idx, member in enumerate(ordered):
            versions.append({
                "path": member["path"],
                "sha256": member["sha256"],
                "bytes": member["bytes"],
                "mtime_ns": member["mtime_ns"],
                "marker": member["_marker_info"]["marker"] or None,
                "supersedes": ordered[idx - 1]["path"] if idx > 0 else None,
                "is_current": idx == len(ordered) - 1,
            })
            member["_chain"] = (chain_id, idx == len(ordered) - 1)
        chains.append({
            "chain_id": chain_id,
            "stem_key": key,
            "extension": ext,
            "count": len(ordered),
            "distinct_hashes": len(hashes),
            "basis": "filename_revision_marker+sha256+mtime",
            "current": versions[-1]["path"],
            "members": versions,
            "note": "Reconstructed from filename markers, content hash and mtime; no text diff.",
        })
    return chains


def render_template(template, values, fallback):
    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError):
        rendered = fallback.format(**values)
    parts = []
    for part in rendered.split("/"):
        if part in ("", ".", ".."):
            continue
        parts.append(sanitize_component(part, {"unicode_form": "NFC",
                                               "forbidden_chars": "<>:\"/\\|?*#%",
                                               "replacement": "_", "whitespace": "_",
                                               "collapse_repeats": True}))
    return "/".join(parts) if parts else "_unnamed"


def add_suffix_to_target(target, suffix):
    parent, name = (target.rsplit("/", 1) + [""])[:2] if "/" in target else ("", target)
    stem, ext = split_name(name)
    result = stem + suffix + ext
    return (parent + "/" + result) if parent else result


def cap_target_length(target, root_len, max_chars, sha):
    if root_len + 1 + len(target) <= max_chars:
        return target, []
    parent, name = (target.rsplit("/", 1) + [""])[:2] if "/" in target else ("", target)
    stem, ext = split_name(name)
    allowed = max_chars - root_len - len(parent) - len(ext) - 11
    if allowed < 8:
        stem = (sha or "nohash")[:8]
    else:
        stem = stem[:allowed].rstrip(" ._-") + "__" + (sha or "nohash")[:8]
    new_target = (parent + "/" + stem + ext) if parent else (stem + ext)
    return new_target, ["path_length_capped"]


def plan_targets(inventory, metadata_by_path, chains, policy, case_id, lib_root,
                 conflicts, skipped):
    naming = policy["naming"]
    fallbacks = naming.get("fallbacks", {})
    chain_map = {}
    for chain in chains:
        for member in chain["members"]:
            chain_map[member["path"]] = (chain["chain_id"], member["is_current"])
    manifest, renamed, plan_actions = [], [], []
    used = {}
    max_path = int(policy.get("caps", {}).get("max_path_chars", 240))
    root_len = len(str(lib_root))

    for index, entry in enumerate(sorted(inventory, key=lambda x: x["path"]), 1):
        fields = metadata_by_path.get(entry["path"], {})
        project_value = fields.get("project", {}).get("value") or fallbacks.get("project", "_unassigned")
        year_value = fields.get("year", {}).get("value") or fallbacks.get("year", "nd")
        project = sanitize_component(str(project_value), naming)
        category = entry["category"]
        filename, reasons = sanitize_filename(entry["name"], naming)
        chain_info = chain_map.get(entry["path"])
        if entry["role"] == "sidecar":
            template = naming["sidecar_template"]
            action = "copy"
        elif chain_info and not chain_info[1]:
            template = naming["archive_template"]
            action = "archive_copy"
        else:
            template = naming["template"]
            action = "copy"
        values = {"case_id": case_id, "project": project, "category": category,
                  "year": str(year_value), "filename": filename,
                  "stem": split_name(filename)[0], "ext": split_name(filename)[1]}
        target = render_template(template, values, "{project}/{filename}")
        target, more = cap_target_length(target, root_len, max_path, entry["sha256"])
        reasons = sorted(set(reasons + more))

        if not entry["readable"] or not entry["sha256"]:
            target = None
            action = "skip"
            status = "skipped_unreadable"
        else:
            key = target.casefold()
            if key in used:
                new_target = add_suffix_to_target(target, "__" + entry["sha256"][:8])
                counter = 2
                while new_target.casefold() in used:
                    new_target = add_suffix_to_target(
                        target, "__%s_%d" % (entry["sha256"][:8], counter))
                    counter += 1
                conflicts.append({
                    "type": "target_collision",
                    "sources": sorted([used[key], entry["path"]]),
                    "proposed_target": target,
                    "resolved_target": new_target,
                    "resolution": "sha256_suffix",
                    "silent_overwrite": False,
                })
                target = new_target
            dest = lib_root / Path(target)
            status = "planned"
            if dest.exists():
                if dest.is_file():
                    existing_hash, _, _, _ = hash_file(dest, int(policy["hash"]["max_hash_bytes"]))
                    if existing_hash == entry["sha256"]:
                        action = "keep_existing"
                        status = "already_present"
                    else:
                        original = target
                        new_target = add_suffix_to_target(target, "__" + entry["sha256"][:8])
                        counter = 2
                        while (lib_root / Path(new_target)).exists() or new_target.casefold() in used:
                            new_target = add_suffix_to_target(
                                original, "__%s_%d" % (entry["sha256"][:8], counter))
                            counter += 1
                        conflicts.append({
                            "type": "existing_target_differs",
                            "source": entry["path"],
                            "existing_target": original,
                            "existing_sha256": existing_hash,
                            "new_sha256": entry["sha256"],
                            "resolved_target": new_target,
                            "resolution": "sha256_suffix_no_overwrite",
                        })
                        target = new_target
                else:
                    new_target = add_suffix_to_target(target, "__" + entry["sha256"][:8])
                    counter = 2
                    while (lib_root / Path(new_target)).exists() or new_target.casefold() in used:
                        new_target = add_suffix_to_target(
                            target, "__%s_%d" % (entry["sha256"][:8], counter))
                        counter += 1
                    conflicts.append({
                        "type": "existing_target_not_file",
                        "source": entry["path"],
                        "existing_target": target,
                        "resolved_target": new_target,
                        "resolution": "sha256_suffix_no_overwrite",
                    })
                    target = new_target
            used[target.casefold()] = entry["path"]

        if reasons:
            renamed.append({
                "source": entry["path"],
                "from_name": entry["name"],
                "to_name": target.rsplit("/", 1)[-1] if target else None,
                "target": target,
                "reasons": reasons,
            })

        manifest.append({
            "id": "F%04d" % index,
            "source": entry["path"],
            "source_name": entry["name"],
            "source_role": entry["role"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "hash_truncated": entry["hash_truncated"],
            "category": category,
            "target": target,
            "target_abs": str(lib_root / Path(target)) if target else None,
            "action": action,
            "status": status,
            "overwrite": False,
            "version_chain": chain_info[0] if chain_info else None,
            "is_current_version": chain_info[1] if chain_info else None,
            "naming_reasons": reasons,
            "metadata_sources": {k: v.get("source") for k, v in fields.items()},
            "_source_abs": entry["_abs"],
        })
        plan_actions.append({
            "seq": index,
            "op": action if action != "keep_existing" else "keep",
            "source": entry["path"],
            "target": target,
            "sha256": entry["sha256"],
            "overwrite": False,
            "preconditions": {"target_absent_or_identical": True},
            "postconditions": {"sha256_equals_source": action in ("copy", "archive_copy")},
            "status": "planned" if status == "planned" else status,
        })
    return manifest, renamed, plan_actions


def _created_dirs(directory):
    missing = []
    current = Path(directory)
    while not current.exists():
        missing.append(str(current))
        if current.parent == current:
            break
        current = current.parent
    return list(reversed(missing))


def copy_no_overwrite(source, target, created_dirs):
    for directory in _created_dirs(Path(target).parent):
        created_dirs.append(directory)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(str(target), flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as out_handle, open(str(source), "rb") as in_handle:
            shutil.copyfileobj(in_handle, out_handle, 1048576)
    except BaseException:
        try:
            os.unlink(str(target))
        except OSError:
            pass
        raise


def execute_plan(manifest, lib_root, policy, applied_records, conflicts, skipped):
    created_files, created_dirs = [], []
    copy_ok = True
    cap = int(policy["hash"]["max_hash_bytes"])
    verify = bool(policy.get("apply", {}).get("verify_sha256_after_copy", True))
    for item in manifest:
        if item["action"] not in ("copy", "archive_copy") or item["status"] == "already_present":
            continue
        if not item["target"] or not item["_source_abs"]:
            continue
        target = lib_root / Path(item["target"])
        try:
            copy_no_overwrite(item["_source_abs"], target, created_dirs)
            if policy.get("apply", {}).get("copy_preserve_times", True):
                try:
                    shutil.copystat(item["_source_abs"], str(target))
                except OSError:
                    pass
            if verify:
                digest, _, _, err = hash_file(target, cap)
                if err or digest != item["sha256"]:
                    try:
                        os.unlink(str(target))
                    except OSError:
                        pass
                    raise OSError("sha256 verification failed: %s" % (err or "digest_mismatch"))
            item["status"] = "applied"
            created_files.append(str(target))
            applied_records.append({"source": item["source"], "target": item["target"],
                                    "sha256": item["sha256"], "verified": verify})
        except FileExistsError:
            item["status"] = "failed_existing"
            copy_ok = False
            conflicts.append({"type": "apply_target_exists", "source": item["source"],
                              "target": item["target"],
                              "resolution": "no_overwrite_left_original"})
        except OSError as exc:
            item["status"] = "failed"
            copy_ok = False
            skipped.append({"kind": "apply", "path": item["source"],
                            "reason": "copy_failed", "error": str(exc)[:300]})
    return copy_ok, created_files, created_dirs


def build_layout(manifest):
    tree = {}
    for item in sorted(manifest, key=lambda x: (x["target"] or "", x["source"])):
        if not item["target"]:
            continue
        node = tree
        parts = item["target"].split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = {"source": item["source"], "sha256": item["sha256"],
                           "bytes": item["bytes"], "action": item["action"]}
    return tree


def build_hashes(inventory):
    return [{"path": e["path"], "sha256": e["sha256"], "bytes": e["bytes"],
             "algorithm": e["hash_algorithm"], "truncated": e["hash_truncated"]}
            for e in sorted(inventory, key=lambda x: x["path"])]


def fingerprint(inventory):
    lines = []
    for entry in sorted(inventory, key=lambda x: x["path"]):
        lines.append("%s|%d|%d|%s" % (entry["path"], entry["bytes"],
                                      entry["mtime_ns"], entry["sha256"] or ""))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def count_regular_files(roots, exclude_keys, policy):
    exclude_dirs = set(policy.get("exclude_dirs", []))
    max_depth = int(policy.get("caps", {}).get("max_depth", 32))
    count = 0
    errors = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if safe_resolve(root) not in exclude_keys:
                count += 1
            continue
        stack = [(root, 0)]
        while stack:
            dirpath, depth = stack.pop()
            try:
                with os.scandir(str(dirpath)) as handle:
                    entries = list(handle)
            except OSError as exc:
                errors.append(str(exc)[:200])
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in exclude_dirs or depth + 1 > max_depth:
                            continue
                        stack.append((Path(entry.path), depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        if safe_resolve(Path(entry.path)) not in exclude_keys:
                            count += 1
                except OSError as exc:
                    errors.append(str(exc)[:200])
    return count, errors


def inputs_unchanged(inventory):
    for entry in inventory:
        try:
            st = os.stat(entry["_abs"], follow_symlinks=False)
            if int(st.st_size) != entry["bytes"] or int(getattr(st, "st_mtime_ns", 0)) != entry["mtime_ns"]:
                return False
        except OSError:
            return False
    return True


def run_selfcheck(result, inventory, manifest, skipped, contract, roots,
                  exclude_keys, policy, snapshot_before, apply_mode):
    checks = []
    inv_paths = {e["path"] for e in inventory}

    bad_hash = [e["path"] for e in inventory
                if e["readable"] and not re.match(r"^[0-9a-f]{64}$", e["sha256"] or "")]
    checks.append({"id": "sha256_for_every_readable_file", "ok": not bad_hash,
                   "detail": "%d bad hash record(s)" % len(bad_hash)})

    fs_count, fs_errors = count_regular_files(roots, exclude_keys, policy)
    extra = {s["path"] for s in skipped
             if s.get("kind") in ("file", "entry") and s.get("path") not in inv_paths}
    accounted = len(inventory) + len(extra)
    checks.append({"id": "counts_match_filesystem", "ok": fs_count == accounted,
                   "detail": "filesystem=%d accounted=%d" % (fs_count, accounted)})

    manifest_sources = {m["source"] for m in manifest}
    targets = [m["target"] for m in manifest if m["target"]]
    unique_targets = len(targets) == len({t.casefold() for t in targets})
    source_match = manifest_sources == inv_paths
    checks.append({"id": "manifest_source_matches_inventory", "ok": source_match,
                   "detail": "%d manifest / %d inventory" % (len(manifest_sources), len(inv_paths))})
    checks.append({"id": "manifest_targets_unique", "ok": unique_targets,
                   "detail": "%d target(s)" % len(targets)})
    hash_match = True
    by_path = {e["path"]: e for e in inventory}
    for item in manifest:
        entry = by_path.get(item["source"])
        if entry and entry["sha256"] != item["sha256"]:
            hash_match = False
            break
    checks.append({"id": "manifest_sha256_matches_inventory", "ok": hash_match,
                   "detail": "source-to-target records checked"})

    missing_contract = [key for key in contract if key not in result]
    checks.append({"id": "contract_keys_present", "ok": not missing_contract,
                   "detail": "%d key(s); missing=%s" % (len(contract), missing_contract)})

    unchanged = inputs_unchanged(inventory)
    checks.append({"id": "inputs_unchanged", "ok": unchanged,
                   "detail": "size and mtime re-read after run"})

    failed_apply = [m["source"] for m in manifest if m["status"].startswith("failed")]
    checks.append({"id": "no_failed_copy", "ok": not failed_apply,
                   "detail": "%d failed" % len(failed_apply)})

    if apply_mode:
        missing_targets = [m["source"] for m in manifest
                           if m["action"] in ("copy", "archive_copy")
                           and m["status"] not in ("applied", "already_present")
                           and m["status"] != "skipped_unreadable"]
        checks.append({"id": "apply_completed", "ok": not missing_targets,
                       "detail": "%d unfinished" % len(missing_targets)})

    honest = True
    if skipped or [c for c in result.get("conflicts", []) if c.get("type") != "stem_ambiguity"]:
        honest = result.get("status") in ("partial", "failed", "insufficient_input")
    checks.append({"id": "status_is_honest", "ok": honest,
                   "detail": "status=%s skipped=%d" % (result.get("status"), len(skipped))})

    core_present = all(result.get(key) not in (None, "") for key in ("case_id", "status"))
    checks.append({"id": "no_placeholder_status", "ok": core_present,
                   "detail": "case_id/status present"})
    return checks


def md_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_review(result, args, selfcheck):
    lines = []
    lines.append("# 运行复核报告 / Run Review")
    lines.append("")
    lines.append("> 本文件由 `scripts/sk_entry.py` 依据本次实际扫描生成；执行 Agent 必须核对后补充或更正，不能只保留模板。")
    lines.append("")
    lines.append("## 1. 运行信息")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|-|-|")
    lines.append("| case_id | `%s` |" % md_cell(result.get("case_id")))
    lines.append("| 模式 | `%s` |" % md_cell(result.get("mode")))
    lines.append("| 状态 | `%s` |" % md_cell(result.get("status")))
    lines.append("| 输入 | `%s` |" % md_cell(args.input))
    lines.append("| 工作目录 | `%s` |" % md_cell(args.work))
    lines.append("| 输出目录 | `%s` |" % md_cell(args.out))
    lines.append("")
    stats = result.get("stats", {})
    lines.append("## 2. 计数")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|-|-|")
    for key in ("files", "readable_files", "bytes", "duplicate_groups",
                "duplicate_extras", "version_chains", "version_members",
                "renamed", "conflicts", "skipped", "unresolved_metadata",
                "plan_actions", "applied_copies"):
        lines.append("| %s | %s |" % (key, md_cell(stats.get(key, 0))))
    lines.append("")
    lines.append("## 3. 自检")
    lines.append("")
    lines.append("| 检查 | 结果 | 说明 |")
    lines.append("|-|-|-|")
    for check in selfcheck:
        lines.append("| %s | %s | %s |" % (
            md_cell(check["id"]), "PASS" if check["ok"] else "FAIL",
            md_cell(check["detail"])))
    lines.append("")
    lines.append("## 4. 契约字段")
    lines.append("")
    lines.append("| 字段 | 映射来源 | 是否存在 |")
    lines.append("|-|-|-|")
    extras = result.get("contract_extras", {})
    for key in result.get("contract_fields", []):
        info = extras.get(key, {})
        lines.append("| `%s` | %s | %s |" % (
            md_cell(key), md_cell(info.get("mapped_from", "-")),
            "是" if key in result else "否"))
    lines.append("")
    lines.append("## 5. 重复与版本")
    lines.append("")
    for group in result.get("duplicates", []):
        lines.append("- 重复组 `%s`：%d 个成员（%s）" % (
            group["sha256"][:12], group["count"], "、".join(group["members"])))
    for chain in result.get("versions", []):
        lines.append("- 版本链 `%s`：%d 个成员，当前版本 `%s`" % (
            chain["chain_id"], chain["count"], chain["current"]))
    if not result.get("duplicates") and not result.get("versions"):
        lines.append("- 未检测到重复组或版本链。")
    lines.append("")
    lines.append("## 6. 跳过、冲突与未解析元数据")
    lines.append("")
    for item in result.get("skipped", []):
        lines.append("- 跳过 [%s] `%s`：%s" % (
            item.get("kind"), item.get("path"), item.get("reason")))
    for item in result.get("conflicts", []):
        lines.append("- 冲突 [%s]：%s" % (item.get("type"), md_cell(item.get("resolution", ""))))
    for item in result.get("unresolved_metadata", []):
        lines.append("- 元数据缺失 `%s`：%s" % (
            item["path"], "、".join(item["missing_fields"])))
    lines.append("")
    lines.append("## 7. 不确定性与限制")
    lines.append("")
    for item in result.get("uncertainty", []):
        lines.append("- %s" % item)
    lines.append("")
    lines.append("## 8. 回滚")
    lines.append("")
    rollback = result.get("rollback_plan", {})
    lines.append("- 输入是否被修改：`%s`" % rollback.get("inputs_modified"))
    lines.append("- 已创建文件：%d 个" % len(rollback.get("created_files", [])))
    lines.append("- 已创建目录：%d 个" % len(rollback.get("created_dirs", [])))
    lines.append("- 回滚方式：%s" % rollback.get("note", ""))
    lines.append("")
    lines.append("## 9. Agent 复核备注")
    lines.append("")
    checks = {c["id"]: c for c in selfcheck}
    stats_map = result.get("stats", {})
    count_check = checks.get("counts_match_filesystem", {"ok": False, "detail": "not run"})
    hash_check = checks.get("sha256_for_every_readable_file", {"ok": False, "detail": "not run"})
    copy_check = checks.get("no_failed_copy", {"ok": False, "detail": "not run"})
    lines.append("- manifest 条数与文件系统计数：inventory=%d，manifest=%d，自检 `%s`（%s）。" % (
        stats_map.get("files", 0), len(result.get("manifest", [])),
        "PASS" if count_check.get("ok") else "FAIL", count_check.get("detail", "")))
    lines.append("- sha256：可读文件 %d/%d 有 64 位 hash，自检 `%s`；复制校验 `%s`（%s）。" % (
        stats_map.get("readable_files", 0), stats_map.get("files", 0),
        "PASS" if hash_check.get("ok") else "FAIL",
        "PASS" if copy_check.get("ok") else "FAIL", copy_check.get("detail", "")))
    lines.append("- 写入：模式 `%s`，applied=`%s`，本次复制 %d 个文件；输入 source_mutation=`%s`。" % (
        result.get("mode"), result.get("applied"),
        stats_map.get("applied_copies", 0),
        result.get("evidence_details", {}).get("source_mutation")))
    lines.append("- 限制：skipped=%d，conflicts=%d，uncertainty=%d 条，均已在上文列出。" % (
        len(result.get("skipped", [])), len(result.get("conflicts", [])),
        len(result.get("uncertainty", []))))
    lines.append("- 执行 Agent 必须用独立命令复算上述计数与至少 3 个 hash（含中文名文件），"
                 "并用实际结果更新本节；若复算不一致，以复算结果为准并说明差异。")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def public_entry(entry):
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def make_summary(case_id, status, inventory, duplicates, chains, conflicts, skipped,
                 manifest, apply_mode):
    readable = sum(1 for e in inventory if e["readable"])
    placements = sum(1 for m in manifest if m["action"] in ("copy", "archive_copy"))
    mode = "apply" if apply_mode else "dry-run"
    return ("%s: %s %s; %d file(s) inventoried (%d readable), %d duplicate group(s), "
            "%d version chain(s), %d conflict(s), %d skipped, %d planned placement(s). "
            "Inputs were only read." % (
                case_id, mode, status, len(inventory), readable, len(duplicates),
                len(chains), len(conflicts), len(skipped), placements))


def execute(args):
    input_dir = Path(args.input)
    if input_dir.is_file() and input_dir.name.lower() in ("case.json", "task.json"):
        input_dir = input_dir.parent
    work_dir = Path(args.work)
    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    apply_mode = bool(args.apply)
    logs, run_log, errors, skipped, conflicts = [], [], [], [], []

    def log(event, **detail):
        logs.append({"seq": len(logs) + 1, "event": event, "detail": detail})

    def phase(name, ok=True, **detail):
        record = {"phase": name, "ok": ok}
        record.update(detail)
        run_log.append(record)

    log("start", input=str(input_dir), work=str(work_dir), out=str(out_dir),
        apply=apply_mode, unknown_args=list(getattr(args, "unknown", [])))

    policy, policy_err = load_policy(args.policy)
    if policy_err:
        errors.append("policy: " + policy_err)
    phase("load_policy", policy_err is None, note=policy_err or "loaded")

    case_path = input_dir / "case.json"
    case, case_err = load_json_file(case_path)
    case_ok = isinstance(case, dict)
    if case_err:
        errors.append("case.json: " + case_err)
        case = {}
    elif not case_ok:
        errors.append("case.json: root is not an object")
        case = {}
    status = "success" if case_ok else "failed"
    apply_case_policy(policy, case)
    contract = extract_contract_keys(case) if case_ok else []
    for contract_name in ("output_contract.json", "contract.json"):
        if contract:
            break
        contract_path = input_dir / contract_name
        if contract_path.is_file():
            contract_obj, contract_err = load_json_file(contract_path)
            if contract_err:
                errors.append("%s: %s" % (contract_name, contract_err))
            elif contract_obj is not None:
                contract = extract_contract_keys({"output_contract": contract_obj})
    case_id = case.get("case_id") if isinstance(case.get("case_id"), str) and case.get("case_id").strip() else None
    if not case_id:
        case_id = "unknown"
        if status != "failed":
            status = "partial"
    phase("load_case", case_ok, case_id=case_id, contract_keys=len(contract))

    roots = resolve_roots(case, input_dir)
    exclude_keys = {safe_resolve(case_path)}
    for name in ("task.md", "task.json", "policy.json",
                 "output_contract.json", "contract.json"):
        candidate = input_dir / name
        if candidate.exists():
            exclude_keys.add(safe_resolve(candidate))
    log("scan_start", roots=[str(r) for r in roots],
        exclude_controls=sorted(Path(x).name for x in exclude_keys))
    inventory = scan_materials(roots, policy, exclude_keys, logs, skipped, errors)
    check_declared(case, input_dir, inventory, skipped)
    phase("scan", True, files=len(inventory), skipped=len(skipped), roots=len(roots))

    snapshot_fp = fingerprint(inventory)
    sidecars, global_map = collect_sidecars(inventory, roots, policy, skipped)
    phase("sidecars", True, attached=len(sidecars), global_rows=len(global_map))

    meta_records, meta_by_path, unresolved = build_metadata(
        inventory, sidecars, global_map, case_metadata(case), policy, skipped)
    phase("metadata", True, records=len(meta_records), unresolved=len(unresolved))

    duplicates, zero_byte = build_duplicates(inventory)
    chains = build_versions(inventory, conflicts)
    phase("analyze", True, duplicate_groups=len(duplicates),
          version_chains=len(chains), conflicts=len(conflicts))

    lib_root = out_dir / policy["apply"]["library_subdir"]
    manifest, renamed, plan_actions = plan_targets(
        inventory, meta_by_path, chains, policy, case_id, lib_root, conflicts, skipped)
    phase("plan", True, manifest=len(manifest), actions=len(plan_actions))

    rollback = {
        "mode": "apply" if apply_mode else "dry_run",
        "inputs_modified": False,
        "created_files": [],
        "created_dirs": [],
        "undo_operations": [],
        "restore_source": "inputs are read-only; no restore needed",
        "note": ("dry-run: nothing was written into the library"
                 if not apply_mode else
                 "delete the listed created files/dirs to revert; never delete inputs"),
    }
    applied_records = []
    apply_ok = True
    if apply_mode:
        apply_ok, created_files, created_dirs = execute_plan(
            manifest, lib_root, policy, applied_records, conflicts, skipped)
        rollback["created_files"] = created_files
        rollback["created_dirs"] = sorted(set(created_dirs))
        rollback["undo_operations"] = (
            [{"op": "remove_file", "path": p} for p in created_files] +
            [{"op": "remove_dir_if_empty", "path": p} for p in rollback["created_dirs"]])
        rollback["note"] = ("delete created files (inputs untouched); created dirs may be "
                            "removed only when empty")
        phase("apply", apply_ok, copied=len(created_files), failed=not apply_ok)
    else:
        phase("apply", True, note="dry-run; no copy performed")

    if status != "failed":
        if not inventory:
            status = "insufficient_input"
        elif skipped or conflicts or unresolved or any(not e["readable"] for e in inventory) \
                or any(e["hash_truncated"] for e in inventory) or not apply_ok:
            status = "partial"
        else:
            status = "success"

    layout = build_layout(manifest)
    hashes = build_hashes(inventory)
    total_bytes = sum(e["bytes"] for e in inventory)
    stats = {
        "files": len(inventory),
        "readable_files": sum(1 for e in inventory if e["readable"]),
        "bytes": total_bytes,
        "duplicate_groups": len(duplicates),
        "duplicate_extras": sum(g["extra_copies"] for g in duplicates),
        "zero_byte_files": len(zero_byte),
        "version_chains": len(chains),
        "version_members": sum(c["count"] for c in chains),
        "renamed": len(renamed),
        "conflicts": len(conflicts),
        "skipped": len(skipped),
        "unresolved_metadata": len(unresolved),
        "plan_actions": len(plan_actions),
        "applied_copies": len(applied_records),
        "truncated_hashes": sum(1 for e in inventory if e["hash_truncated"]),
    }
    source_mutation = "none" if inputs_unchanged(inventory) else "detected"
    evidence = {
        "input_root": str(input_dir),
        "material_roots": [str(r) for r in roots],
        "excluded_controls": sorted(Path(x).name for x in exclude_keys),
        "hash_algorithm": policy["hash"]["algorithm"],
        "hash_byte_cap": policy["hash"]["max_hash_bytes"],
        "file_count": len(inventory),
        "total_bytes": total_bytes,
        "input_fingerprint": snapshot_fp,
        "source_mutation": source_mutation,
        "library_root": str(lib_root),
        "policy_sha256": hashlib.sha256(
            json.dumps(policy, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "applied": apply_mode,
    }
    uncertainty = [
        "Version chains use filename revision markers, content hash and mtime; no text diff is performed.",
        "Duplicate files are reported with sha256 and kept; nothing is deleted.",
        "Metadata is taken only from sidecars, filenames, text headers or case defaults; missing values stay null.",
        "Binary or format-level corruption is not parsed; files are hashed and copied byte-for-byte.",
        "Directory categories are extension-based; task-specific layout must come from the case policy or task.md.",
    ]
    if any(e["hash_truncated"] for e in inventory):
        uncertainty.append("Files larger than the hash cap were hashed on a prefix only.")
    if skipped:
        uncertainty.append("Some entries were skipped or unreadable; see skipped records.")
    if conflicts:
        uncertainty.append("Name or target conflicts were resolved with deterministic suffixes, not human judgement.")
    if apply_mode and not policy["safety"].get("allow_move", False):
        uncertainty.append("Move was not used; every ingest is a verified copy so sources stay intact.")

    summary = make_summary(case_id, status, inventory, duplicates, chains, conflicts,
                           skipped, manifest, apply_mode)
    inventory_public = [public_entry(e) for e in inventory]
    payload_result = {
        "inventory": inventory_public,
        "manifest": manifest,
        "duplicates": duplicates,
        "versions": chains,
        "renamed": renamed,
        "skipped": skipped,
        "conflicts": conflicts,
        "unresolved_metadata": unresolved,
        "plan_actions": plan_actions,
        "applied": apply_mode,
        "rollback_plan": rollback,
        "logs": logs,
        "stats": stats,
        "layout": layout,
    }
    result = {
        "case_id": case_id,
        "status": status,
        "mode": "apply" if apply_mode else "dry_run",
        "inventory": inventory_public,
        "manifest": manifest,
        "duplicates": duplicates,
        "versions": chains,
        "version_chains": chains,
        "renamed": renamed,
        "skipped": skipped,
        "conflicts": conflicts,
        "unresolved_metadata": unresolved,
        "plan_actions": plan_actions,
        "applied": apply_mode,
        "rollback_plan": rollback,
        "logs": logs,
        "uncertainty": uncertainty,
        "run_log": run_log,
        "evidence": evidence,
        "evidence_details": evidence,
        "stats": stats,
        "stats_details": stats,
        "summary": summary,
        "metadata": meta_records,
        "layout": layout,
        "hashes": hashes,
        "selfcheck": [],
        "policy_echo": {
            "hash": policy["hash"],
            "caps": policy["caps"],
            "naming_template": policy["naming"]["template"],
            "archive_template": policy["naming"]["archive_template"],
            "sidecar_template": policy["naming"]["sidecar_template"],
            "allow_move": policy["safety"].get("allow_move", False),
            "allow_delete": policy["safety"].get("allow_delete", False),
            "overwrite": policy["safety"].get("overwrite", "never"),
        },
        "contract_fields": contract,
        "contract_extras": {},
        "contract_unmapped": [],
        "skill_version": VERSION,
        "errors": errors,
    }

    values = {
        "case_id": case_id,
        "status": status,
        "mode": "apply" if apply_mode else "dry_run",
        "dry_run": not apply_mode,
        "applied": apply_mode,
        "errors": errors,
        "uncertainty": uncertainty,
        "inventory": inventory_public,
        "manifest": manifest,
        "duplicates": duplicates,
        "versions": chains,
        "renamed": renamed,
        "skipped": skipped,
        "conflicts": conflicts,
        "unresolved_metadata": unresolved,
        "plan_actions": plan_actions,
        "rollback_plan": rollback,
        "logs": logs,
        "summary": summary,
        "evidence": manifest,
        "sources": logs,
        "metadata": meta_records,
        "layout": layout,
        "hashes": hashes,
        "stats": stats,
        "result": payload_result,
    }
    extras = {}
    unmapped = []
    for key in contract:
        canon = ALIAS.get(norm_key(key))
        if canon is not None:
            value = values.get(canon)
            result[key] = value
            source = {"evidence": "manifest", "sources": "logs"}.get(canon, canon)
            extras[key] = {"mapped_from": source, "note": "direct alias"}
        else:
            value, note = best_effort(key, values)
            result[key] = value
            if value is None:
                unmapped.append(key)
            extras[key] = {"mapped_from": None, "note": note}
    result["contract_extras"] = extras
    result["contract_unmapped"] = unmapped

    selfcheck = run_selfcheck(result, inventory, manifest, skipped, contract, roots,
                              exclude_keys, policy, snapshot_fp, apply_mode)
    result["selfcheck"] = selfcheck
    if "selfcheck" in contract:
        result["selfcheck"] = selfcheck

    log("selfcheck", passed=sum(1 for c in selfcheck if c["ok"]), total=len(selfcheck))
    log("done", status=status, applied=apply_mode)

    # Persist result first; this is the contract artifact.
    result_path = out_dir / "result.json"
    try:
        write_json(result_path, result)
        log("result_written", path=str(result_path))
    except OSError as exc:
        errors.append("cannot write result.json: %s" % exc)
        try:
            write_json(work_dir / "result.json", result)
        except OSError:
            pass

    # Work-area artifacts.
    try:
        write_json(work_dir / "plan" / "inventory.json", inventory_public)
        write_json(work_dir / "plan" / "manifest.json", manifest)
        write_json(work_dir / "plan" / "plan_actions.json", plan_actions)
        write_json(work_dir / "plan" / "duplicates.json", duplicates)
        write_json(work_dir / "plan" / "versions.json", chains)
        write_json(work_dir / "plan" / "logs.json", logs)
        write_json(work_dir / "plan" / "rollback_plan.json", rollback)
    except OSError as exc:
        log("work_write_failed", error=str(exc)[:200])

    if apply_mode:
        try:
            write_json(out_dir / "apply_manifest.json",
                       {"case_id": case_id, "manifest": manifest,
                        "applied_copies": applied_records, "stats": stats})
            write_json(out_dir / "rollback.json", rollback)
        except OSError as exc:
            log("apply_artifact_write_failed", error=str(exc)[:200])

    if policy.get("write_review", True):
        try:
            review = render_review(result, args, selfcheck)
            with open(str(out_dir / "run-review.md"), "w", encoding="utf-8") as fh:
                fh.write(review)
        except OSError as exc:
            log("review_write_failed", error=str(exc)[:200])

    return 0


def best_effort(key, values):
    nk = norm_key(key)
    heuristics = [
        (("dup", "重复"), "duplicates"),
        (("version", "revision", "版本"), "versions"),
        (("conflict", "冲突"), "conflicts"),
        (("skip", "unread", "跳过"), "skipped"),
        (("manifest", "move", "rename", "入库", "移动"), "manifest"),
        (("file", "inventory", "item", "record", "state", "文件"), "inventory"),
        (("summary", "report", "报告", "摘要"), "summary"),
        (("log", "source", "provenance", "日志", "来源"), "logs"),
        (("rollback", "undo", "回滚"), "rollback_plan"),
        (("metadata", "元数据"), "metadata"),
        (("layout", "tree", "目录"), "layout"),
        (("hash", "sha", "哈希"), "hashes"),
        (("stat", "count", "统计"), "stats"),
        (("evidence", "证据", "校验"), "manifest"),
    ]
    for needles, canon in heuristics:
        if any(needle in nk for needle in needles):
            return values.get(canon), "heuristic:" + canon
    return None, "no supported producer; null retained"


def write_fallback(out_arg, message):
    try:
        out_dir = Path(out_arg)
        out_dir.mkdir(parents=True, exist_ok=True)
        fallback = {
            "case_id": "unknown",
            "status": "failed",
            "mode": "dry_run",
            "inventory": [], "manifest": [], "duplicates": [], "versions": [],
            "version_chains": [], "renamed": [], "skipped": [], "conflicts": [],
            "unresolved_metadata": [], "plan_actions": [], "applied": False,
            "rollback_plan": {"inputs_modified": False, "created_files": [],
                              "created_dirs": [], "note": "not started"},
            "logs": [], "uncertainty": [message], "run_log": [],
            "evidence": {"source_mutation": "none"}, "stats": {},
            "summary": "failed before scan: " + message,
            "metadata": [], "layout": {}, "hashes": [], "selfcheck": [],
            "contract_fields": [], "contract_extras": {}, "contract_unmapped": [],
            "skill_version": VERSION, "result": {}, "errors": [message],
        }
        write_json(out_dir / "result.json", fallback)
    except OSError:
        pass


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Deterministic research-library ingest steward (stdlib only)")
    parser.add_argument("--input", default="/input",
                        help="input directory containing case.json and materials")
    parser.add_argument("--work", default="/app/work", help="working directory")
    parser.add_argument("--out", "--output", dest="out", default="/app/output",
                        help="output directory for result.json and run-review.md")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="copy planned files into <out>/library; default is dry-run")
    parser.add_argument("--policy", default=None, help="optional policy.json override")
    args, unknown = parser.parse_known_args(argv)
    args.unknown = unknown
    return args


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out_arg = "/app/output"
    for index, token in enumerate(argv):
        if token in ("--out", "--output") and index + 1 < len(argv):
            out_arg = argv[index + 1]
        elif token.startswith("--out="):
            out_arg = token.split("=", 1)[1]
        elif token.startswith("--output="):
            out_arg = token.split("=", 1)[1]
    try:
        args = parse_args(argv)
        return execute(args)
    except SystemExit:
        write_fallback(out_arg, "argument parsing exited")
        return 0
    except BaseException as exc:  # last-resort guard: never fail the harness run
        write_fallback(out_arg, "unhandled exception: %s" % type(exc).__name__)
        return 0


build_aliases()

if __name__ == "__main__":
    sys.exit(main())
