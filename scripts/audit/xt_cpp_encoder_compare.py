#!/usr/bin/env python3
"""Read-only M1 cross-check against compiled *original* Gearmulator C++ encoder bodies.

Extracts the actual State::createWaveData/createTableData implementations and
updateChecksum from the *locked local upstream*; compiles an isolated harness
outside Git in runs/, compares synthetic vectors with our Python codec.

Does not edit Gearmulator, touch any ROM/firmware/dump, or send MIDI.
Generated C++ (upstream-derived) and executable are temporary, not published.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "7f9a9806b7b3326379a39a2008c6dc92519191df"
LOCKED_XTSTATE_SHA256 = "14BF10536A85EE5901381D216E027B74DBA38171CCAC47CDA42B2484C246CD2A"


def extract_cpp_function(text: str, signature: str) -> str:
    """Select entire original method by signature and balanced braces."""
    pos = text.find(signature)
    if pos < 0:
        raise ValueError(f"upstream function not found: {signature}")
    # Do not accept shadow mention in a comment: require a qualified C++ signature.
    first = text.rfind("\n", 0, pos) + 1
    prefix = text[first:pos].strip()
    if prefix not in ("SysEx", "static bool", "bool"):
        raise ValueError(f"unexpected upstream function signature: {signature}: {prefix!r}")
    brace = text.find("{", pos)
    semi = text.find(";", pos)
    if brace < 0 or (semi != -1 and semi < brace):
        raise ValueError(f"definition not found for: {signature}")
    level = 0
    for i in range(brace, len(text)):
        char = text[i]
        if char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level == 0:
                return text[first:i+1].strip()
    raise ValueError(f"unbalanced function: {signature}")


def verify_upstream(gear: Path) -> dict:
    if not (gear / ".git").exists():
        raise ValueError(f"missing upstream Git clone: {gear}")
    def git(*args: str) -> str:
        x = subprocess.run(["git", "-C", str(gear), *args], capture_output=True, text=True, check=True)
        return x.stdout.strip()
    sha = git("rev-parse", "HEAD")
    if sha != LOCKED_COMMIT:
        raise ValueError(f"Gearmulator HEAD changed: expected {LOCKED_COMMIT}, got {sha}")
    status = git("status", "--porcelain")
    if status:
        raise ValueError("upstream worktree not clean; refusing unreviewed source")
    path = gear / "source/waldi/xt/xtLib/xtState.cpp"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest().upper()
    if digest != LOCKED_XTSTATE_SHA256:
        raise ValueError(f"source SHA-256 differs from audited baseline: {digest}")
    header = (gear / "source/waldi/xt/xtLib/xtState.h").read_text(encoding="utf-8-sig")
    midi = (gear / "source/waldi/xt/xtLib/xtMidiTypes.h").read_text(encoding="utf-8-sig")
    commons = (gear / "source/waldi/common/wLib/wMidiTypes.h").read_text(encoding="utf-8-sig")
    constraints = [(midi, "WaveDump      = 0x12"), (midi, "WaveCtlDump   = 0x13"),
                   (midi, "WaveDumpP     = 0x19"), (midi, "WaveCtlDumpP  = 0x1a"),
                   (commons, "IdWaldorf = 0x3e"), (commons, "IdDeviceOmni = 0x7f")]
    for source, marker in constraints:
        if not re.search(r"\s+".join(map(re.escape, marker.split())), source, re.I):
            raise ValueError(f"unexpected upstream enum: {marker}")
    return {"sha": sha, "xtstate_sha256": digest,
            "state": raw.decode("utf-8-sig"), "header": header}


def create_harness(state: str, header: str) -> str:
    # The implementations below are extracted byte-for-byte from the checked upstream source.
    wave_method = extract_cpp_function(state, "State::createWaveData(")
    table_method = extract_cpp_function(state, "State::createTableData(")
    checksum_method = extract_cpp_function(header, "updateChecksum(SysEx&")
    if "static bool updateChecksum" not in checksum_method:
        raise ValueError("wrong checksum implementation extracted")
    return r'''#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>
#include <initializer_list>
#include <iterator>
#include <iostream>
#include <iomanip>
#include <string>
namespace wLib { constexpr uint8_t IdWaldorf = 0x3e; constexpr uint8_t IdDeviceOmni = 0x7f; }
namespace xt {
    constexpr uint8_t IdMw2 = 0x0e;
    enum class SysexCommand : uint8_t { WaveDump = 0x12, WaveCtlDump = 0x13, WaveDumpP = 0x19, WaveCtlDumpP = 0x1a };
    struct WaveId {
        uint16_t v{};
        WaveId() = default;
        explicit WaveId(uint16_t x): v(x) {}
        uint16_t rawId() const { return v; }
    };
    using WaveData = std::array<int8_t,128>;
    using TableData = std::array<WaveId,64>;
    using SysEx = std::vector<uint8_t>;
    struct State {
''' + checksum_method + r'''
    static SysEx createWaveData(const WaveData&, uint16_t, bool);
    static SysEx createTableData(const TableData&, uint32_t, bool);
    };
''' + wave_method + '\n\n' + table_method + r'''
}
int main() {
    char kind;
    while (std::cin >> kind) {
        int id;
        if (!(std::cin >> id)) return 2;
        xt::SysEx bytes;
        if (kind == 'W') {
            xt::WaveData w{};
            for (int i=0; i<64; ++i) {
                int x;
                if (!(std::cin >> x) || x < -128 || x > 127) return 3;
                w[i] = static_cast<int8_t>(x);
            }
            bytes = xt::State::createWaveData(w, static_cast<uint16_t>(id), false);
        } else if (kind == 'T') {
            xt::TableData t{};
            for (int i=0; i<64; ++i) {
                int x;
                if (!(std::cin >> x) || x < 0 || x > 65535) return 4;
                t[i] = xt::WaveId(static_cast<uint16_t>(x));
            }
            bytes = xt::State::createTableData(t, static_cast<uint32_t>(id), false);
        } else return 5;
        for (uint8_t b: bytes) {
            std::cout << std::hex << std::setfill('0') << std::setw(2) << (int)b;
        }
        std::cout << std::dec << '\n';
    }
    return 0;
}
'''


def synthetic_vectors() -> list[tuple[str,int,list[int]]]:
    rng = random.Random(0x58544D31)
    cases: list[tuple[str,int,list[int]]] = []
    for id_, samples in [
        (1000, [0]*64), (1249, [-128]*64), (1001, [127]*64),
        (1100, [i-32 for i in range(64)]),
    ]:
        cases.append(("W", id_, samples))
    for i in range(12):
        cases.append(("W", [1000,1249,1077,1189][i%4], [rng.randrange(-128,128) for _ in range(64)]))
    for id_, ids in [(96, [1000]*61+[0xFFFF,0xDEAD,0xBEEF]),
                     (127, list(range(1189,1250))+[1,2,3])]:
        cases.append(("T", id_, ids))
    for i in range(12):
        vals=[rng.randrange(65536) for _ in range(64)]
        cases.append(("T", [96,127,100,111][i%4], vals))
    return cases


def expected_python(vectors: list[tuple[str,int,list[int]]]) -> list[str]:
    from xtwavetable.codec_xt.sysex import encode_table_dump, encode_wave_dump
    from xtwavetable.model import Table, Wave
    out=[]
    for kind, id_, values in vectors:
        if kind == "W":
            data = encode_wave_dump(id_, Wave.from_half_cycle(values))
        else:
            data = encode_table_dump(id_, Table(tuple(values)))
        out.append(data.hex())
    return out


def run_test(gear: Path, work: Path, compiler: str) -> dict:
    provenance = verify_upstream(gear)
    reference = create_harness(provenance["state"], provenance["header"])
    work.mkdir(parents=True, exist_ok=True)
    vectors=synthetic_vectors()
    expected=expected_python(vectors)
    cpp_file=work / "gear_xt_encoder_oracle.cpp"
    cpp_file.write_text(reference,encoding="utf-8")
    cc = compiler
    if cc == "auto":
        cc = "cl" if shutil.which("cl") else "g++"
    found=shutil.which(cc)
    if not found:
        raise RuntimeError(f"compiler {cc} missing (open VS Code MSVC x64 terminal)")
    exe=work/("gear_xt_encoder_oracle.exe" if sys.platform=="win32" else "gear_xt_encoder_oracle")
    if cc == "cl":
        command=[found,"/nologo","/std:c++17","/EHsc","/Od",str(cpp_file),"/Fe:"+str(exe),"/link","/nologo"]
    else:
        command=[found,"-std=c++17","-O0",str(cpp_file),"-o",str(exe)]
    built=subprocess.run(command,cwd=work,capture_output=True,text=True,timeout=120)
    if built.returncode != 0:
        raise RuntimeError("C++ oracle compiler error: "+(built.stdout+"\n"+built.stderr)[-3500:])
    payload="".join(f"{kind} {id_} "+" ".join(map(str,values))+"\n" for kind,id_,values in vectors)
    run=subprocess.run([str(exe)],input=payload,capture_output=True,text=True,timeout=30)
    if run.returncode != 0:
        raise RuntimeError(f"C++ oracle exited {run.returncode}: "+run.stderr[-1000:])
    received=[x.strip().lower() for x in run.stdout.splitlines() if x.strip()]
    if len(received)!=len(expected):
        raise RuntimeError(f"C++ oracle returned {len(received)} lines; expected {len(expected)}")
    mismatches=[{"index":i,"kind":vectors[i][0],"id":vectors[i][1]}
                for i,(a,b) in enumerate(zip(received,expected)) if a!=b]
    return {"schema":"xtwavetable.m1.cpp_reference.v1", "upstream_commit":provenance["sha"],
            "upstream_source_sha256":provenance["xtstate_sha256"],
            "reference":"Original Gearmulator State::createWaveData/createTableData/updateChecksum compiled in minimal shim",
            "compiler":cc, "vector_count":len(vectors),"passed":len(vectors)-len(mismatches),
            "failed":len(mismatches),"mismatches":mismatches,
            "scope":"synthetic input; standard WaveDump/TableDump only; no MIDI/hardware"}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument("--compiler",choices=["auto","cl","g++"],default="auto")
    parser.add_argument("--report",type=Path,default=None)
    args=parser.parse_args()
    root=args.root.resolve()
    report=args.report or (root/"reports"/("XT_M1_CPP_REFERENCE_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".json"))
    if not report.is_absolute(): report=root/report
    if report.exists():
        parser.error(f"refusing overwrite: {report}")
    workroot=root/"runs"
    if not workroot.exists(): parser.error(f"runs/ directory not found: {workroot}")
    try:
        with tempfile.TemporaryDirectory(dir=workroot,prefix="m1_cpp_oracle_") as temp:
            result=run_test(root/"upstream/gearmulator",Path(temp),args.compiler)
        result["generated_utc"]=datetime.now(timezone.utc).isoformat()
        report.parent.mkdir(parents=True,exist_ok=True)
        with report.open("x",encoding="utf-8") as fp:
            json.dump(result,fp,indent=2)
            fp.write("\n")
        print(f"[{ 'PASS' if result['failed']==0 else 'FAIL' }] C++ Gearmulator encoder cross-check: {result['passed']}/{result['vector_count']}")
        print(f"[INFO] Reference SHA-256: {result['upstream_source_sha256']}")
        print(f"[INFO] Report: {report}")
        return 0 if result['failed']==0 else 1
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as err:
        print(f"[BLOCKED] {type(err).__name__}: {err}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
