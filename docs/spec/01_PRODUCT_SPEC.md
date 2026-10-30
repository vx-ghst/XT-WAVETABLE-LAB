# 01 — Product requirements / cahier des charges

**Version:** 0.1 draft — requirements, not completion claims.

## Goal

Turn an authorized source WAV into optimized Waldorf Microwave XT-compatible custom waves and one or more 64-position wavetable definitions, export standard MIDI SysEx (plus optional MIDI and Serum comparison assets), and preview the results with two separate modes: *stock Waldorf OS 2.33* and *Tallent Edition*. The same canonical XT waves/tables must serve both modes.

## Personas/use cases

- Sound designer: convert a recorded vowel, synthesizer sweep, bell, noise or movement into a useful evolving wavetable.
- Preservation: import and compare existing user waves and tables from real XT dumps **read-only**, then export without overwriting them.
- Research: compare extraction methods and firmware renderers in repeatable offline A/B experiments.

## P1 — Minimum viable converter (MVP)

| ID | Requirement | Acceptance / observable result |
|---|---|---|
| F-001 | Import PCM WAV mono/stereo 16/24-bit and float where decoder supports it | Validate channels, rate, integrity; clear error on unsupported data |
| F-002 | Select source range; choose mono/downmix; remove DC; optional normalize | Original never modified; settings recorded in manifest |
| F-003 | Analyze pitch/periodicity, spectral flux and time evolution | A report explains whether signal is tonal/noise/transient; no false 'high fidelity' promises |
| F-004 | Generate candidate sequences of 8, 16, 32, optionally up to 61 distinct waves | Exact cardinality and selection indices recorded; manual selection override |
| F-005 | Convert candidate cycles to XT wave constraints (signed 8-bit, 128-point antisymmetric cycle, 64-point transmitted half) | All output waves satisfy round-trip and symmetry rules; handle -128 saturation correctly |
| F-006 | Create 64-position XT tables; only positions 0–60 user-definable, 61–63 reserved | No writes to reserved positions; monotonic/repeated placement selectable |
| F-007 | Export standard Waldorf SysEx wave+table packets, with valid checksums and slot addressing | Cross-parse results; stable hashes for fixed synthetic fixtures |
| F-008 | Read existing SysEx dumps, list used/free/conflicting user slots | Report before generating a write plan; never overwrite original dump |
| F-009 | Preview quickly without firmware | Mark as **approximate synthesizer preview**, never label 'hardware exact' |
| F-010 | Provide deterministic CLI and JSON report | Same inputs + version + config yield same generated wave bytes and manifest |

## P2 — Xenia firmware-based rendering

| ID | Requirement | Acceptance |
|---|---|---|
| X-001 | Stock OS 2.33 Xenia headless render | Boot real ROM legally provided; deterministic WAV with MIDI notes at fixed 40 kHz internal rate (output may be resampled) |
| X-002 | Read-only patch loading/preview | Inject candidate data into sandboxed emulator, NOT real XT; verify no mutations to source ROM files |
| X-003 | Tallent Edition renderer | Must actually boot correct Tallent firmware under Xenia and demonstrate new features; otherwise hide/disable as 'unverified' |
| X-004 | Comparison reports | Same candidate waves, preset, MIDI performance and render parameters; export difference metrics + listenable A/B |
| X-005 | Error/approximation disclosure | Separate preview approximation, firmware-emulated rendering and physical hardware validation statuses |

## Later release requirements

- Optional clean GUI (PySide6 after CLI validation), editable slot maps, visual time/frequency/spectrogram comparisons.
- Optional Serum WAV export **separately**; it is not the canonical route and cannot bypass XT geometry.
- Optional hardware SysEx readback/upload: **OFF by default**; backup, destination diff, explicit confirmation and post-upload readback are mandatory.
- Optional Tallent-specific sound parameter presets: interpolation modes, Warp, X-Mod, separate Osc2 table. They are **not changes to the wave/table codec** unless real-world testing proves otherwise.

## Explicit non-goals (v1)

- Not a sampler, not a WAV player on XT, not transcription of rhythms or syllables.
- Not a complete reimplementation of the XT firmware, filter or FX engine.
- No automatic firmware flashing or EEPROM programming.
- No guarantee that the output sounds exactly like the original source recording.
- No destructive changes to XT or original dumps.

## Non-functional requirements

- Windows 11 x64 first, offline-capable, reproducible and no network during audio processing.
- Unit tests run on synthetic audio without firmware; integration tests use private data conditionally.
- Must cope with silent files, clipped input, DC offset, noninteger periods, high-frequency loss, mono/stereo phase cancellation, malformed SysEx and ROM mismatch.
- Preserve original data, source filenames and SHA-256 in private manifests; public test reports must exclude contents, private paths and recordings.
- Performance target to be set after a baseline on available hardware; avoid inventing latency requirements before profiling.

## Definition of quality

Rank candidates on interpretable metrics (spectral preservation, continuity between waves, tonal stability, aliasing estimates, timbral coverage). Expose trade-offs and allow audition. A single 'quality score' is **not** objective proof of perceptual excellence.
