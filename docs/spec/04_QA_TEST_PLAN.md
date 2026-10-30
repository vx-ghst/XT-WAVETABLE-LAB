# 04 — QA / certification protocol

## Test groups

- `T_FORMAT`: exact SysEx header/command/addresses/7-bit-nibble/checksum; table references and reserved slots.
- `T_ROUNDTRIP`: wave->SysEx->wave and table->SysEx->table; random seeded edge cases including signed min/max and symmetry.
- `T_NEGATIVE`: truncated SysEx, wrong manufacturer/model/command/device, wrong checksum, invalid IDs, duplicate/overlapping frames, oversized WAV, silent or clipped inputs.
- `T_ANALYSIS`: known synthetic F0 sine/chirp, phase-shifted harmonics, noise, attacks, stereo antiphase and silence.
- `T_OPTIMIZER`: stable deterministic seed, no out-of-range IDs, dedup collision-free mapping, source-range validity, bounded budgets.
- `T_XENIA_STOCK`: ROM boot, pure offline render, identical preset/control/MIDI across samples, deterministic hash policy (or tolerances, if float output nondeterministic).
- `T_TALLENT`: same baseline samples with extra features OFF, then specific feature ON positive controls; test candidate OS in emulator is not guaranteed yet.
- `T_HARDWARE`: physical readback and auditory/digital reference recordings, only after explicit opt-in.

## Rules

1. `PASS`, `FAIL`, `SKIP`, `BLOCKED`, `NOT_RUN` are distinct statuses.
2. A test is certified only when executable inputs, observed output, reference SHA/version and logs exist.
3. Active QA executes from scratch on every release even if previously passed.
4. Historical tests can be removed/archived if redundant, or promoted to active regression if they cover unique failure modes.
5. Do not use perceptual guesses as digital proof. Compare Xenia to physical XT with controlled audio recording when that claim is required.
6. All proprietary test assets are local; public CI uses generated synthetic fixtures.

## Release gate

- No red active checks.
- No unresolved critical file corruption / unintended hardware write path.
- Git commit SHA + dependency versions + every input hash in a private signed or immutable run report.
- Release notes say exactly what is not verified, especially Tallent emulation and physical device parity.
