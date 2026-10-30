# 03 — Roadmap by evidence-gated milestones

Milestones are not deadlines. A stage is DONE only when exit criteria are verified with preserved logs. Re-run the *entire active suite* on every release; keep archived tests only if they establish unique historical behavior not in the active suite.

## M0 — Inputs / provenance / research baseline

**Deliverables:** source tree cloned at pinned commits; legal/private inputs inventory and SHA-256; dump parsing feasibility; stock ROM sufficiency assessment; architecture decision approved.

**Exit:** original dumps and OS update identified, no proprietary binary in Git, references recorded, format invariants tied to source locations. Hardware can remain disconnected.

## M1 — XT codec and read-only dump inspector

**Deliverables:** native data model, parsers, checksum and creators for wave/table messages, dump inventory including reserved/occupied wave IDs; synthetic test generator.

**Exit:** 100% active codec tests pass, including random roundtrip, malformed/corrupt negative tests, checksums, boundary IDs, 61–63 reserved handling, no writes; existing dumps parsed without crashes. Cross-check at least one vector with Gearmulator's encoder output.

## M2 — Deterministic WAV conversion MVP

**Deliverables:** WAV parser, crop, downmix/DC handling, pitch/segment analysis, 2–3 candidate methods, 8/16/32/61 wave sets, optimizers, exported standard `.syx` and JSON provenance.

**Exit:** fixed fixtures reproduce byte-for-byte hashes and correct valid SysEx; intentional failures produce clear diagnostics. Audio quality scores are labelled heuristic.

## M3 — Fast preview and batch QA

**Deliverables:** approximate preview engine, simulation of wavetable-position interpolation and transitions between successive XT Waves, A/B output export, batch analysis, automated technical reports and active regression suite. Inspect clicks/phase jumps, RMS/timbre discontinuity and sweep trajectories; do not present this approximation as firmware-identical.

**Exit:** auditable comparisons; known approximation gaps documented. No false claims of XT identity.

## M4 — Xenia stock renderer adapter

**Deliverables:** pinned Gearmulator fork or tool wrapper, headless MIDI/SysEx render to WAV, tests for native ROM boot, deterministic same-input output and no mutation of originals. Compare M3 interpolation/transition predictions with actual stock-OS emulation under matched sweep settings, documenting the differences.

**Exit:** valid stock 2.33 emulator output with reproducible render; Xenia version/ROM hash in manifest; no hardware required to run routine tests.

## M5 — Tallent Edition feasibility and second renderer

**Deliverables:** verify patcher output against authenticated Waldorf update, investigate whether Xenia can boot patched OS (full ROM dependency), render old-feature parity A/B, test new interpolations and Warp/X-Mod.

**Exit:** second renderer activated only if firmware boots and expected parameter modes are independently observed. Otherwise mark blocked with an explicit technical reason; converter remains useful under stock OS.

## M6 — GUI and export package

**Deliverables:** optional Windows desktop UI, wave/time/spectrum visualization, comparison and explicit export confirmation. Test clean local install.

**Exit:** UI parity with CLI, no destructive hardware operations, packaged executable retains license/firmware separation.

## M7 — Optional physical device validation & uploader

**Deliverables:** hardware reference captures, measured variance Xenia-vs-XT, controlled SysEx upload with full backup/readback and restore test.

**Exit:** hardware transfer tested on known disposable slots with user authorization. Firmware flashing is **not** part of this milestone.

## Priority now

**Current position (30 October 2026):** M0 and M1 completed; M1 published at `8dd121e`. M2.1–M2.8 passed local Windows regression with **250 PASS, 0 SKIP, 0 FAIL, 0 ERROR** after resolving Windows symlink privilege error 1314; M2 publication review pending. The next planned milestone is M3 after controlled M2 publication. Do not spend effort yet on GUI, advanced neural conversion, firmware patch integration or destructive MIDI upload. Their interfaces are specified to prevent future rework.
