"""Static checks that stand in for hassfest/HACS until CI runs on GitHub."""
from __future__ import annotations

import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).parents[1]
MANIFEST = json.loads((ROOT / "custom_components/neatsvor_s600/manifest.json").read_text("utf-8"))
HACS = json.loads((ROOT / "hacs.json").read_text("utf-8"))
REPO = "https://github.com/mikozaman/neatsvor_s600_v2"


def test_manifest_keys_sorted_as_hassfest_expects():
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_manifest_required_fields():
    assert MANIFEST["domain"] == "neatsvor_s600"
    assert MANIFEST["integration_type"] == "device"
    assert MANIFEST["iot_class"] == "cloud_push"
    assert MANIFEST["config_flow"] is True
    assert MANIFEST["codeowners"] == ["@mikozaman"]
    assert MANIFEST["documentation"] == REPO
    assert MANIFEST["issue_tracker"] == f"{REPO}/issues"
    assert MANIFEST["version"] == "0.3.0"
    assert MANIFEST["requirements"] == ["paho-mqtt>=2.1.0,<3"]


def test_hacs_json():
    assert HACS["name"] == "Neatsvor S600"
    assert HACS["homeassistant"] == "2025.1.0"
    assert HACS["render_readme"] is True


def test_workflow_has_the_four_validation_jobs():
    workflow = yaml.safe_load((ROOT / ".github/workflows/validate.yml").read_text("utf-8"))
    assert set(workflow["jobs"]) == {"hassfest", "hacs", "ruff", "pytest"}
