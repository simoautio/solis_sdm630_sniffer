"""Every translation must cover exactly the keys in strings.json."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "custom_components/solis_sdm630_sniffer"
STRINGS = json.loads((ROOT / "strings.json").read_text())


def load(name):
    """Import one pure module without the Home Assistant package __init__."""
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def paths(node, prefix=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from paths(value, (*prefix, key))
    else:
        assert isinstance(node, str) and node.strip(), prefix
        yield prefix


def test_english_matches_strings():
    assert json.loads((ROOT / "translations/en.json").read_text()) == STRINGS


@pytest.mark.parametrize("language", ["fi"])
def test_translation_has_every_key(language):
    translation = json.loads((ROOT / f"translations/{language}.json").read_text())
    assert set(paths(translation)) == set(paths(STRINGS))


def test_every_register_has_an_entity_name():
    names = STRINGS["entity"]["sensor"]
    for register in load("registers").REGISTERS.values():
        assert names[register.key]["name"] == register.name
    for register in load("inverter_registers").REGISTERS:
        assert names[f"inverter_{register.key}"]["name"] == register.name
