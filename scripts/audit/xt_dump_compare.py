#!/usr/bin/env python3
"""XT-WAVETABLE-LAB: offline read-only comparison of two MW II/XT SysEx Everything dumps.

Only standard-library Python, no MIDI output and no firmware modification.
Reports metadata/counts/differences, never raw presets/waves.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

COMMANDS = {
    0x10: ("single", 265, 256, range(0, 256)),
    0x11: ("multi", 265, 128, range(0, 128)),
    0x12: ("wave", 137, 250, range(1000, 1250)),
    0x13: ("table", 265, 32, range(96, 128)),
    0x14: ("global", 39, 1, range(0, 1)),
}


def load_dump(path: Path) -> dict:
    payload = path.read_bytes()
    errors = []
    events = []
    if not payload or payload[0] != 0xF0:
        errors.append("Missing initial F0")
    if payload.count(0xF0) != payload.count(0xF7):
        errors.append("Number of F0 and F7 markers differs")
    start = 0
    while start < len(payload):
        if payload[start] != 0xF0:
            errors.append(f"Unexpected byte before SysEx at offset {start}")
            break
        end = payload.find(b"\xf7", start + 1)
        if end == -1:
            errors.append(f"Unterminated SysEx at offset {start}")
            break
        m = payload[start:end + 1]
        if 0xF0 in m[1:-1]:
            errors.append(f"Embedded F0 at offset {start}")
        events.append(m)
        start = end + 1
    by_key = {}
    for ordinal, m in enumerate(events):
        if len(m) < 9:
            errors.append(f"Message {ordinal} too short")
            continue
        if m[:3] != bytes([0xF0, 0x3E, 0x0E]) or m[-1] != 0xF7:
            errors.append(f"Message {ordinal} is not a Microwave II/XT SysEx dump")
            continue
        if any(x >= 128 for x in m[1:-1]):
            errors.append(f"Message {ordinal} contains non-7-bit MIDI data")
        cmd = m[4]
        if cmd not in COMMANDS:
            errors.append(f"Message {ordinal} has unsupported command 0x{cmd:02X}")
            continue
        name, expected_len, _, ids = COMMANDS[cmd]
        if len(m) != expected_len:
            errors.append(f"Message {ordinal} ({name}) length {len(m)} != {expected_len}")
            continue
        idx = (m[5] << 7) | m[6]
        if idx not in ids:
            errors.append(f"Message {ordinal} ({name}) unexpected index {idx}")
        if cmd in (0x12, 0x13) and any(value > 0x0F for value in m[7:-2]):
            errors.append(f"Message {ordinal} ({name}) contains data outside 4-bit nibbles")
        if (sum(m[7:-2]) & 0x7F) != m[-2]:
            errors.append(f"Message {ordinal} ({name}) checksum mismatch")
        key = (cmd, idx)
        if key in by_key:
            errors.append(f"Duplicate {name} index {idx}")
        by_key[key] = m

    counts = {}
    missing = {}
    for cmd, (name, _, expected_count, ids) in COMMANDS.items():
        actual = sum(k[0] == cmd for k in by_key)
        counts[name] = {"actual": actual, "expected": expected_count}
        missed = [i for i in ids if (cmd, i) not in by_key]
        if missed:
            missing[name] = missed
            errors.append(f"{name}: {len(missed)} expected entries missing")
    return {
        "file": path.name,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "event_count": len(events),
        "all_checks_pass": len(errors) == 0,
        "counts": counts,
        "errors": errors,
        "missing_ids": missing,
        "by_key": by_key,
    }


def decode_table(raw: bytes) -> list[int]:
    return [((raw[7 + i * 4] << 12) |
             (raw[8 + i * 4] << 8) |
             (raw[9 + i * 4] << 4) |
             raw[10 + i * 4]) for i in range(64)]


def compare(older: dict, newer: dict) -> dict:
    d = {}
    a, b = older["by_key"], newer["by_key"]
    keys = sorted(set(a) | set(b))
    for cmd, (name, _size, _count, _ids) in COMMANDS.items():
        changed_ids = []
        raw_diffs = 0
        payload_diffs = 0
        checksum_diffs = 0
        for key in keys:
            if key[0] != cmd:
                continue
            x, y = a.get(key), b.get(key)
            if x is None or y is None:
                changed_ids.append(key[1])
                continue
            if x == y:
                continue
            changed_ids.append(key[1])
            raw_diffs += sum(u != v for u, v in zip(x, y))
            payload_diffs += sum(u != v for u, v in zip(x[7:-2], y[7:-2]))
            checksum_diffs += x[-2] != y[-2]
        d[name] = {
            "changed_count": len(changed_ids),
            "changed_ids": changed_ids,
            "changed_raw_bytes": raw_diffs,
            "changed_payload_bytes": payload_diffs,
            "changed_checksum_bytes": checksum_diffs,
        }

    before, after = a.get((0x13, 127)), b.get((0x13, 127))
    specific = None
    if before and after:
        tb, ta = decode_table(before), decode_table(after)
        specific = {
            "table_id": 127,
            "older_positions_0_to_60_wave_ids": tb[:61],
            "newer_positions_0_to_60_wave_ids": ta[:61],
            "older_reserved_positions_61_to_63": tb[61:],
            "newer_reserved_positions_61_to_63": ta[61:],
            "newer_uses_sequential_user_waves_1189_to_1249": ta[:61] == list(range(1189, 1250)),
        }
    return {"by_command": d, "table_127": specific,
            "total_changed_messages": sum(v["changed_count"] for v in d.values()),
            "total_unchanged_messages": sum(a.get(k) == b.get(k) for k in keys)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--older", required=True, type=Path, help="Earlier Everything .syx file")
    ap.add_argument("--newer", required=True, type=Path, help="Later Everything .syx file")
    ap.add_argument("--out", required=True, type=Path, help="JSON report in a private local directory")
    args = ap.parse_args()
    a, b = load_dump(args.older), load_dump(args.newer)
    result = {
        "project": "XT-WAVETABLE-LAB",
        "step": "24.1 — dump format and differential audit",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "Read only; no SysEx output; no firmware access or hardware access.",
        "older": {k: v for k, v in a.items() if k != "by_key"},
        "newer": {k: v for k, v in b.items() if k != "by_key"},
        "comparison": compare(a, b),
        "limitations": [
            "Valid checksums and complete ID ranges do not prove restorability on physical hardware.",
            "Values in user slots may contain uninitialized or sentinel data; musical validity is not certified.",
            "No vendor hardware writes or emulator injections were performed.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=== XT-WAVETABLE-LAB / READ-ONLY EVERYTHING DUMP COMPARISON ===")
    for k, item in (("OLDER", a), ("NEWER", b)):
        print(f"{k}: {item['file']} : {item['byte_size']} bytes / {item['event_count']} messages / valid={item['all_checks_pass']}")
    for name, val in result["comparison"]["by_command"].items():
        print(f"{name.upper():7s}: {val['changed_count']} changed messages")
    print(f"TOTAL: {result['comparison']['total_changed_messages']} changed, {result['comparison']['total_unchanged_messages']} unchanged")
    print(f"Report: {args.out}")
    if a["errors"] or b["errors"]:
        print("[FAIL] Dump validation errors; read the report")
        return 1
    print("[PASS] Complete structure, all checksums valid, differential report created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
