"""M2 audio ingestion; deliberately separate from XT SysEx and rendering."""

from .wav_reader import WavAudio, WavFormatError, decode_wav, read_wav

__all__ = ["WavAudio", "WavFormatError", "decode_wav", "read_wav"]
