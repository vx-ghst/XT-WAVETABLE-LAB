# XT Wavetable Lab

Research and development workspace for Waldorf Microwave XT
wavetable analysis, conversion and experimentation.

## Project goals

- Study wavetable representation in the Microwave XT.
- Analyze relevant Gearmulator / Xenia implementation details.
- Research conversion of WAV audio into wavetable data.
- Develop reproducible tools and validation tests.
- Keep experiments separate from original firmware.

## Current status

Initial development environment configured and validated.

No custom wavetable conversion engine is published yet.

## Development environment

- Windows 11
- Visual Studio Code
- Git
- CMake and Ninja
- Microsoft Visual C++ 2026 (x64)
- Gearmulator / Xenia

Validated locally:

- Xenia VST3 Release compilation
- Xenia VST3 Debug compilation
- Loading and audio output in Ableton Live 12
- C++ debugger attachment
- Source breakpoints and variable inspection

## Upstream dependency

Gearmulator:
https://github.com/dsp56300/gearmulator

Reference commit:
7f9a9806b7b3

Gearmulator is maintained separately from this repository.

To obtain the upstream source code:

```powershell
git clone https://github.com/dsp56300/gearmulator.git upstream/gearmulator
git -C upstream/gearmulator checkout 7f9a9806b7b3
```

## Local build example

Open a Visual Studio x64 developer terminal.

```powershell
cmake -S upstream/gearmulator `
  -B build/gearmulator-xenia-debug `
  -G Ninja `
  -DCMAKE_BUILD_TYPE=Debug

cmake --build build/gearmulator-xenia-debug `
  --target xtJucePlugin_VST3 `
  --parallel 2
```

The upstream project controls the generated plugin paths.

## Excluded from this repository

- Proprietary firmware and ROM images
- Firmware dumps and SysEx data
- Local audio samples
- Compiled VST3 / CLAP binaries
- PDB symbols and build artifacts
- Private configuration and credentials

No Waldorf firmware or ROM files are distributed here.

## Development policy

- Preserve original firmware.
- Prefer reversible, testable experiments.
- Validate modifications in the emulator first.
- Document compatibility and limitations.
- Do not assume hardware compatibility without testing.

## Acknowledgements

Gearmulator / Xenia:
https://github.com/dsp56300/gearmulator

This project is independent and is not an official
Waldorf or Gearmulator release.

## License

A license for original XT Wavetable Lab code has not
yet been selected. Third-party components retain their
respective licenses.