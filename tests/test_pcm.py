from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from libmpv_runtime.errors import VerificationError
from libmpv_runtime.pcm import create_fixture, main, verify_gain


def _scale_wav(source: Path, destination: Path, factor: float) -> None:
    with wave.open(str(source), mode="rb") as input_file:
        parameters = input_file.getparams()
        frames = input_file.readframes(input_file.getnframes())
    scaled = bytearray()
    for (sample,) in struct.iter_unpack("<h", frames):
        scaled.extend(struct.pack("<h", round(sample * factor)))
    with wave.open(str(destination), mode="wb") as output:
        output.setparams(parameters)
        output.writeframes(scaled)


def test_gain_probe_measures_post_filter_pcm(tmp_path: Path) -> None:
    original = tmp_path / "original.wav"
    processed = tmp_path / "processed.wav"
    create_fixture(original, seconds=0.5)
    _scale_wav(original, processed, 0.5)
    measured = verify_gain(
        original,
        processed,
        expected_db=-6.0206,
        tolerance_db=0.05,
    )
    assert measured == pytest.approx(-6.0206, abs=0.01)


def test_gain_probe_rejects_property_write_without_audio_change(tmp_path: Path) -> None:
    original = tmp_path / "original.wav"
    unchanged = tmp_path / "unchanged.wav"
    create_fixture(original, seconds=0.25)
    unchanged.write_bytes(original.read_bytes())
    with pytest.raises(VerificationError, match="outside"):
        verify_gain(
            original,
            unchanged,
            expected_db=-6.0206,
            tolerance_db=0.1,
        )


def test_pcm_cli_creates_fixture_and_reports_gain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original = tmp_path / "original.wav"
    processed = tmp_path / "processed.wav"
    assert main(["fixture", "--output", str(original), "--seconds", "0.1"]) == 0
    _scale_wav(original, processed, 0.5)
    assert (
        main(
            [
                "verify-gain",
                "--original",
                str(original),
                "--processed",
                str(processed),
                "--expected-db",
                "-6.0206",
                "--tolerance-db",
                "0.05",
            ]
        )
        == 0
    )
    assert "measured-gain-db=" in capsys.readouterr().out
