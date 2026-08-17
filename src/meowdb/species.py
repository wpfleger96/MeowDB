from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from meowdb.models import ProcessorConfig, SegmentationConfig


@dataclass(frozen=True)
class SpeciesConfig:
    fmin: float  # Hz, fingerprint bandpass lower cutoff (similarity.py)
    fmax: float  # Hz, fingerprint bandpass upper cutoff
    # Read-only view: a frozen dataclass must not hand out a mutable shared dict
    segmentation: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


SPECIES_REGISTRY: dict[str, SpeciesConfig] = {
    "cat": SpeciesConfig(fmin=250.0, fmax=8000.0),  # empty overrides -> pure defaults
    # Dog fingerprints keep 60-3500Hz (growl fundamentals through bark harmonics), but
    # detection starts at 150Hz — 60-150Hz admits HVAC rumble and handling thumps into
    # the VAD, and growls are out of detection scope. The highpass >=4500Hz reference
    # leaves a 1kHz guard gap so Butterworth skirts don't leak species energy into it.
    "dog": SpeciesConfig(
        fmin=60.0,
        fmax=3500.0,
        segmentation=MappingProxyType(
            {
                "band_low_hz": 150.0,
                "classifier": "canine",
                "reference_mode": "highpass",
                "reference_cutoff_hz": 4500.0,
                "min_silence_ms": 250,  # a bark volley merges into one segment
                "min_segment_ms": 60,  # single short bark
                "max_segment_ms": 15000,  # howl bouts
            }
        ),
    ),
}

DEFAULT_SPECIES = "cat"


def get_species_config(species: str) -> SpeciesConfig:
    """Return SpeciesConfig for species, falling back to DEFAULT_SPECIES if unknown."""
    return SPECIES_REGISTRY.get(species, SPECIES_REGISTRY[DEFAULT_SPECIES])


def processor_config_for_species(species: str) -> ProcessorConfig:
    """Build a ProcessorConfig from the species registry.

    The fingerprint band (fmin/fmax) seeds the detection band, but per-species
    segmentation overrides win — for dogs the two diverge (fingerprints 60-3500Hz,
    detection 150-3500Hz). Overrides are validated against SegmentationConfig, which
    forbids unknown keys, so a typoed key raises here instead of silently yielding
    cat defaults. Canine classifier knobs nest under a "canine" key.
    """
    sc = get_species_config(species)
    params: dict[str, object] = {
        "band_low_hz": sc.fmin,
        "band_high_hz": sc.fmax,
        **sc.segmentation,
    }
    return ProcessorConfig(segmentation=SegmentationConfig.model_validate(params))
