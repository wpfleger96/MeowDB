from __future__ import annotations

import os
import struct
import wave

from pathlib import Path

from meowdb.db import MeowDB


def _make_wav(path: Path) -> None:
    """Write a 1-second silent mono WAV at 44100 Hz."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<" + "h" * 44100, *([0] * 44100)))


def _make_mp3(path: Path) -> None:
    """Write a minimal fake MP3 with an ID3 header."""
    # ID3v2.3 header: "ID3" + version 2.3 + flags 0 + syncsafe size 0
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")


def _waveform(seed: int) -> list[float]:
    return [abs(0.5 * ((j + seed) % 10 - 5) / 5) for j in range(100)]


def main() -> None:
    data_dir_env = os.environ.get("MEOWDB_DATA_DIR")
    if not data_dir_env:
        raise RuntimeError("MEOWDB_DATA_DIR environment variable is required")

    data_dir = Path(data_dir_env)
    db_path = data_dir / "meowdb.sqlite"
    wav_dir = data_dir / "audio" / "wav"
    mp3_dir = data_dir / "audio" / "mp3"

    wav_dir.mkdir(parents=True, exist_ok=True)
    mp3_dir.mkdir(parents=True, exist_ok=True)

    db = MeowDB(db_path)
    try:
        # MeowDB.__init__ auto-seeds Squishy (cat) when the animals table is empty.
        # Reuse that row rather than inserting a duplicate.
        squishy_id = db.get_animals()[0]["id"]

        thrasher_id = db.add_animal("Thrasher", "cat")
        slushie_id = db.add_animal("Slushie", "dog")

        sounds = [
            # Squishy (cat) — 3 sounds
            {
                "animal_id": squishy_id,
                "timestamp": "2026-01-01T10:00:00",
                "duration_ms": 800,
                "labels": ["happy"],
                "peak_dbfs": -8.0,
                "species_energy_ratio": 3.1,
                "plays": 12,
            },
            {
                "animal_id": squishy_id,
                "timestamp": "2026-01-02T10:00:00",
                "duration_ms": 1200,
                "labels": ["hungry", "loud"],
                "peak_dbfs": -5.0,
                "species_energy_ratio": 2.8,
                "plays": 7,
            },
            {
                "animal_id": squishy_id,
                "timestamp": "2026-01-03T10:00:00",
                "duration_ms": 450,
                "labels": ["happy"],
                "peak_dbfs": -12.0,
                "species_energy_ratio": 2.2,
                "plays": 3,
            },
            # Thrasher (cat) — 2 sounds
            {
                "animal_id": thrasher_id,
                "timestamp": "2026-01-04T10:00:00",
                "duration_ms": 2100,
                "labels": [],
                "peak_dbfs": -15.0,
                "species_energy_ratio": 1.8,
                "plays": 0,
            },
            {
                "animal_id": thrasher_id,
                "timestamp": "2026-01-05T10:00:00",
                "duration_ms": 600,
                "labels": ["sleepy"],
                "peak_dbfs": -20.0,
                "species_energy_ratio": 1.5,
                "plays": 1,
            },
            # Slushie (dog) — 2 sounds
            {
                "animal_id": slushie_id,
                "timestamp": "2026-01-06T10:00:00",
                "duration_ms": 950,
                "labels": ["playful"],
                "peak_dbfs": -10.0,
                "species_energy_ratio": 2.5,
                "plays": 4,
            },
            {
                "animal_id": slushie_id,
                "timestamp": "2026-01-07T10:00:00",
                "duration_ms": 700,
                "labels": [],
                "peak_dbfs": -18.0,
                "species_energy_ratio": 1.2,
                "plays": 0,
            },
        ]

        for i, sound in enumerate(sounds):
            stem = f"sound-{i + 1:02d}"
            wav_path = wav_dir / f"{stem}.wav"
            mp3_path = mp3_dir / f"{stem}.mp3"

            _make_wav(wav_path)
            _make_mp3(mp3_path)

            sound_id = db.add(
                {
                    "animal_id": sound["animal_id"],
                    "timestamp": sound["timestamp"],
                    "duration_ms": sound["duration_ms"],
                    "labels": sound["labels"],
                    "wav_path": str(wav_path),
                    "mp3_path": str(mp3_path),
                    "waveform_data": _waveform(i),
                    "peak_dbfs": sound["peak_dbfs"],
                    "species_energy_ratio": sound["species_energy_ratio"],
                }
            )

            for _ in range(sound["plays"]):
                db.increment_play_count(sound_id)

        animals = db.get_animals()
        print(
            f"Seeded {len(sounds)} sounds across {len(animals)} animals "
            f"({', '.join(a['name'] for a in animals)}) into {db_path}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
