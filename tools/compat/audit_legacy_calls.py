#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect Community Shaders call sites without loading Skyrim or modifying files.

Address Library formats 1/2 follow the decoder in the pinned CommonLibSSE-NG
src/REL/IDDB.cpp. PE parsing uses the Microsoft PE/COFF layout. This is an
inventory and opcode check, not a certificate of ABI or runtime compatibility.
Never commit game executables, personal logs, or generated reports to GitHub.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct


def read_value(stream: io.BytesIO, fmt: str) -> int:
    size = struct.calcsize(fmt)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated Address Library")
    return struct.unpack(fmt, data)[0]


def read_address_library(path: Path) -> tuple[tuple[int, ...], dict[int, int]]:
    """Decode an existing SE/AE Address Library, keeping RVAs independent of ASLR."""
    stream = io.BytesIO(path.read_bytes())
    if read_value(stream, "<I") not in (1, 2):
        raise ValueError("Only Address Library formats 1 and 2 are supported")
    version = tuple(read_value(stream, "<I") for _ in range(4))
    name_len = read_value(stream, "<I")
    if name_len > 4096 or len(stream.read(name_len)) != name_len:
        raise ValueError("Invalid Address Library module name")
    pointer_size, count = read_value(stream, "<I"), read_value(stream, "<I")
    if pointer_size != 8 or not 0 < count < 2_000_000:
        raise ValueError("Invalid Address Library pointer size or entry count")

    def decode(kind: int, previous: int) -> int:
        if kind == 0:
            return read_value(stream, "<Q")
        if kind == 1:
            return previous + 1
        if kind in (2, 3):
            delta = read_value(stream, "<B")
            return previous + delta if kind == 2 else previous - delta
        if kind in (4, 5):
            delta = read_value(stream, "<H")
            return previous + delta if kind == 4 else previous - delta
        if kind in (6, 7):
            return read_value(stream, "<H" if kind == 6 else "<I")
        raise ValueError(f"Invalid Address Library encoding {kind}")

    entries: dict[int, int] = {}
    prev_id = prev_offset = 0
    for _ in range(count):
        kind = read_value(stream, "<B")
        entry_id = decode(kind & 15, prev_id)
        offset_kind = kind >> 4
        scaled = bool(offset_kind & 8)
        offset = decode(offset_kind & 7, prev_offset // 8 if scaled else prev_offset)
        if scaled:
            offset *= 8
        if entry_id < 0 or offset < 0 or entry_id in entries:
            raise ValueError("Invalid or duplicate Address Library entry")
        entries[entry_id] = offset
        prev_id, prev_offset = entry_id, offset
    if stream.read(1):
        raise ValueError("Unexpected trailing Address Library data")
    return version, entries


class PEImage:
    """Read x64 PE section bytes at RVAs; never execute or patch the input."""

    def __init__(self, path: Path) -> None:
        self.data = path.read_bytes()
        if self.data[:2] != b"MZ":
            raise ValueError("Input is not a PE executable")
        pe = self.unpack("<I", 0x3C)
        if self.data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("Invalid PE signature")
        machine, count = struct.unpack_from("<HH", self.data, pe + 4)
        optional_size = self.unpack("<H", pe + 20)
        optional = pe + 24
        if machine != 0x8664 or self.unpack("<H", optional) != 0x20B:
            raise ValueError("Input must be an x64 PE32+ executable")
        self.image_base = self.unpack("<Q", optional + 24)
        self.image_size = self.unpack("<I", optional + 56)
        self.sections = []
        for index in range(count):
            header = optional + optional_size + 40 * index
            name = self.data[header:header + 8].rstrip(b"\0").decode("ascii", errors="replace")
            virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", self.data, header + 8)
            characteristics = self.unpack("<I", header + 36)
            if raw + raw_size > len(self.data):
                raise ValueError("PE section extends beyond the input file")
            self.sections.append((name, rva, virtual_size, raw, raw_size, characteristics))

    def unpack(self, fmt: str, offset: int) -> int:
        if offset < 0 or offset + struct.calcsize(fmt) > len(self.data):
            raise ValueError("Invalid PE header offset")
        return struct.unpack_from(fmt, self.data, offset)[0]

    def code_at(self, rva: int, size: int = 16) -> tuple[str, bytes]:
        for name, start, _, raw, raw_size, flags in self.sections:
            delta = rva - start
            if 0 <= delta and delta + size <= raw_size:
                if not flags & 0x20000000:
                    raise ValueError(f"RVA 0x{rva:X} belongs to non-executable section {name}")
                return name, self.data[raw + delta:raw + delta + size]
        raise ValueError(f"RVA 0x{rva:X} has no file-backed executable bytes")


NUMBER = r"(?:0x[0-9a-fA-F]+|[0-9]+)"
CALL = re.compile(
    r"stl::write_thunk_call<(?P<hook>[^;\n]+?)>\(\s*"
    r"REL::(?:RelocationID|VariantID)\((?P<ids>[^)]+)\)\.address\(\)\s*\+\s*"
    r"(?:(?:REL::Relocate|REL::VariantOffset|Util::VersionedRelocation::Select)"
    r"\((?P<offsets>[^)]+)\)(?:\.offset\(\))?|(?P<constant>" + NUMBER + r"))\s*\)",
    re.MULTILINE,
)


def ae_value(text: str) -> int:
    parts = [x.strip() for x in text.split(",")]
    if len(parts) < 2 or not re.fullmatch(NUMBER, parts[1]):
        raise ValueError(f"Expression needs manual review: {text}")
    return int(parts[1], 0)


def inspect_calls(root: Path, entries: dict[int, int], image: PEImage | None) -> tuple[list[dict], list[dict]]:
    """Inventory literal ID-plus-offset calls and report every unparsed call separately."""
    calls, manual = [], []
    paths = sorted(p for folder in (root / "src", root / "include") for p in folder.rglob("*")
                   if p.suffix in (".cpp", ".h", ".hpp"))
    for path in paths:
        source = path.read_text(encoding="utf-8-sig")
        consumed: set[int] = set()
        for match in CALL.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            consumed.add(line)
            row = {"file": path.relative_to(root).as_posix(), "line": line,
                   "hook": match["hook"].strip(), "status": "unverified"}
            try:
                entry_id = ae_value(match["ids"])
                offset = int(match["constant"], 0) if match["constant"] else ae_value(match["offsets"])
                row.update(id=entry_id, function_rva=hex(entries[entry_id]), offset=hex(offset))
                rva = entries[entry_id] + offset
                row["rva"] = hex(rva)
                if image:
                    section, data = image.code_at(rva)
                    indirect = bool(re.search(r",\s*6$", row["hook"]))
                    valid = data[:2] == b"\xff\x15" if indirect else data[:1] == b"\xe8"
                    row.update(section=section, bytes=data.hex(" "),
                               expected="FF 15 disp32" if indirect else "E8 disp32",
                               status="call_opcode_matches" if valid else "mismatch")
                    if valid and not indirect:
                        row["original_target_rva"] = hex(rva + 5 + struct.unpack_from("<i", data, 1)[0])
            except (KeyError, ValueError) as exc:
                row.update(status="manual_review", error=str(exc))
            calls.append(row)
        for match in re.finditer(r"stl::write_thunk_call<", source):
            line = source.count("\n", 0, match.start()) + 1
            if line not in consumed:
                manual.append({"file": path.relative_to(root).as_posix(), "line": line})
    return calls, manual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--address-library", type=Path)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database = args.address_library or args.source / "extern/CommonLibSSE-NG/tests/REL/versionlib-1-6-353-0.bin"
    version, entries = read_address_library(database)
    if version != (1, 6, 353, 0):
        raise ValueError(f"Expected 1.6.353.0, got {version}")
    image = PEImage(args.exe) if args.exe else None
    calls, manual = inspect_calls(args.source, entries, image)
    report = {
        "runtime": ".".join(map(str, version)),
        "address_library_entries": len(entries),
        "exe_provided": bool(image),
        "limitations": ["Opcode matches do not validate original function signatures or hook semantics.",
                        "Raw patches, detours, vtable hooks and unresolved expressions require separate review.",
                        "This tool does not modify source, game files, or runtime memory."],
        "calls": calls,
        "unparsed_calls": manual,
    }
    if image:
        report["exe_sha256"] = hashlib.sha256(image.data).hexdigest()
        report["exe_md5"] = hashlib.md5(image.data).hexdigest()
        report["image_size"] = hex(image.image_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    counts = {status: sum(c["status"] == status for c in calls) for status in sorted({c["status"] for c in calls})}
    print(json.dumps({"entries": len(entries), "calls": len(calls), "status": counts, "manual": len(manual)}, sort_keys=True))
    return 1 if any(c["status"] in ("mismatch", "manual_review") for c in calls) or manual else 0


if __name__ == "__main__":
    raise SystemExit(main())
