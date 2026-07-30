from __future__ import annotations

import argparse
import math
import struct
import wave
from array import array
from pathlib import Path

from .errors import VerificationError


def create_fixture(path: Path, *, seconds: float = 4.0, sample_rate: int = 48_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(seconds * sample_rate)
    samples = array("h")
    for index in range(frame_count):
        time = index / sample_rate
        section = index / frame_count
        amplitude = 0.12 if section < 0.25 else 0.55 if section < 0.75 else 0.22
        envelope = min(1.0, index / 480.0, (frame_count - index) / 480.0)
        value = int(32767 * amplitude * envelope * math.sin(2.0 * math.pi * 997.0 * time))
        samples.extend((value, value))
    with wave.open(str(path), mode="wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def _rms(path: Path) -> tuple[float, int]:
    try:
        with wave.open(str(path), mode="rb") as source:
            if source.getsampwidth() != 2:
                raise VerificationError(f"{path} is not 16-bit PCM")
            frames = source.getnframes()
            channels = source.getnchannels()
            data = source.readframes(frames)
    except (OSError, wave.Error) as error:
        raise VerificationError(f"cannot read WAV {path}: {error}") from error
    sample_count = frames * channels
    if sample_count == 0 or len(data) != sample_count * 2:
        raise VerificationError(f"{path} contains no complete samples")
    total = 0.0
    for (sample,) in struct.iter_unpack("<h", data):
        normalized = sample / 32768.0
        total += normalized * normalized
    return math.sqrt(total / sample_count), frames


def verify_gain(
    original: Path,
    processed: Path,
    *,
    expected_db: float,
    tolerance_db: float,
) -> float:
    original_rms, original_frames = _rms(original)
    processed_rms, processed_frames = _rms(processed)
    if original_rms <= 0.0 or processed_rms <= 0.0:
        raise VerificationError("RMS must be positive")
    if abs(original_frames - processed_frames) > 4_800:
        raise VerificationError(
            f"decoded frame count changed unexpectedly: {original_frames} -> {processed_frames}"
        )
    measured_db = 20.0 * math.log10(processed_rms / original_rms)
    if abs(measured_db - expected_db) > tolerance_db:
        raise VerificationError(
            f"measured gain {measured_db:.3f} dB is outside "
            f"{expected_db:.3f} +/- {tolerance_db:.3f} dB"
        )
    return measured_db


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m libmpv_runtime.pcm")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture")
    fixture.add_argument("--output", required=True, type=Path)
    fixture.add_argument("--seconds", type=float, default=4.0)
    verify = commands.add_parser("verify-gain")
    verify.add_argument("--original", required=True, type=Path)
    verify.add_argument("--processed", required=True, type=Path)
    verify.add_argument("--expected-db", required=True, type=float)
    verify.add_argument("--tolerance-db", type=float, default=0.35)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "fixture":
        create_fixture(arguments.output, seconds=arguments.seconds)
        print(arguments.output)
        return 0
    measured = verify_gain(
        arguments.original,
        arguments.processed,
        expected_db=arguments.expected_db,
        tolerance_db=arguments.tolerance_db,
    )
    print(f"measured-gain-db={measured:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
