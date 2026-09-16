import random
from pathlib import Path

import pytest

from stargarden.manifest import DiscreteMotion, ManifestError, load_manifest


def test_load_and_pick(assets: Path) -> None:
    m = load_manifest(assets)
    assert m.beds[0].path.name == "bed.wav"
    assert m.discretes[0].motion is DiscreteMotion.FLYBY
    assert m.music[0].title == "Song" and m.music[0].theme == "aurora"
    assert m.thunder[0].path.name == "ping.wav" and m.pick_thunder(random.Random(0)) is m.thunder[0]
    rng = random.Random(0)
    assert m.pick_bed(rng) is m.beds[0]
    assert m.pick_bed(rng, avoid=m.beds[0]) is m.beds[0]  # only one: avoid can't exclude everything
    assert m.pick_music(rng) is m.music[0]


def test_missing_file_and_manifest(assets: Path, tmp_path: Path) -> None:
    (assets / "manifest.toml").write_text('[[beds]]\nfile = "beds/nope.wav"\n')
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(assets)
    with pytest.raises(ManifestError, match="no manifest"):
        load_manifest(tmp_path)
