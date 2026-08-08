from __future__ import annotations

from dataclasses import dataclass

from meowdb.models import ProcessorConfig, SegmentationConfig


@dataclass(frozen=True)
class SpeciesConfig:
    fmin: float  # Hz, discriminator/fingerprint bandpass lower cutoff
    fmax: float  # Hz, bandpass upper cutoff


SPECIES_REGISTRY: dict[str, SpeciesConfig] = {
    "cat": SpeciesConfig(fmin=250.0, fmax=8000.0),  # today's hardcoded values
    "dog": SpeciesConfig(fmin=60.0, fmax=3500.0),  # growl fundamentals ~60Hz through bark harmonics
}

DEFAULT_SPECIES = "cat"


def get_species_config(species: str) -> SpeciesConfig:
    """Return SpeciesConfig for species, falling back to DEFAULT_SPECIES if unknown."""
    return SPECIES_REGISTRY.get(species, SPECIES_REGISTRY[DEFAULT_SPECIES])


def processor_config_for_species(species: str) -> ProcessorConfig:
    """Build a ProcessorConfig with bandpass limits from the species registry."""
    sc = get_species_config(species)
    return ProcessorConfig(
        segmentation=SegmentationConfig(
            band_low_hz=sc.fmin,
            band_high_hz=sc.fmax,
        )
    )
