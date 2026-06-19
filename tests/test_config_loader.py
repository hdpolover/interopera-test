import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")


def test_load_config_firm_a():
    from src.compute.config_loader import load_config
    config = load_config(
        os.path.join(CONFIG_DIR, "base.yaml"),
        os.path.join(CONFIG_DIR, "firm_a.yaml"),
    )
    assert config.firm_id == "firm_a"
    assert config.non_ig.include_fallen_angels is False
    assert config.concentration.gre.group_key == "issuer"
    assert config.output.utilization_format == "percent_1dp"


def test_load_config_firm_b():
    from src.compute.config_loader import load_config
    config = load_config(
        os.path.join(CONFIG_DIR, "base.yaml"),
        os.path.join(CONFIG_DIR, "firm_b.yaml"),
    )
    assert config.firm_id == "firm_b"
    assert config.non_ig.include_fallen_angels is True
    assert config.concentration.gre.group_key == "parent_issuer"
    assert config.output.utilization_format == "truncated_bps"


def test_missing_required_knob_raises_validation_error():
    import tempfile, yaml
    from src.compute.config_loader import load_config
    from pydantic import ValidationError
    # firm yaml missing non_ig.include_fallen_angels
    firm_yaml = {"firm_id": "firm_test", "concentration": {"gre": {"group_key": "issuer"}},
                 "output": {"utilization_format": "percent_1dp"}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(firm_yaml, f)
        firm_path = f.name
    base_yaml = {"limits": {}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(base_yaml, f)
        base_path = f.name
    with pytest.raises((ValidationError, KeyError, TypeError)):
        load_config(base_path, firm_path)


def test_config_hash_is_deterministic():
    from src.compute.config_loader import load_config, effective_config_hash
    config = load_config(
        os.path.join(CONFIG_DIR, "base.yaml"),
        os.path.join(CONFIG_DIR, "firm_a.yaml"),
    )
    h1 = effective_config_hash(config)
    h2 = effective_config_hash(config)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_firm_a_hash_differs_from_firm_b():
    from src.compute.config_loader import load_config, effective_config_hash
    config_a = load_config(
        os.path.join(CONFIG_DIR, "base.yaml"),
        os.path.join(CONFIG_DIR, "firm_a.yaml"),
    )
    config_b = load_config(
        os.path.join(CONFIG_DIR, "base.yaml"),
        os.path.join(CONFIG_DIR, "firm_b.yaml"),
    )
    assert effective_config_hash(config_a) != effective_config_hash(config_b)


def test_invalid_group_key_raises():
    import tempfile, yaml
    from src.compute.config_loader import load_config
    from pydantic import ValidationError
    firm_yaml = {
        "firm_id": "firm_bad",
        "non_ig": {"include_fallen_angels": False},
        "concentration": {"gre": {"group_key": "INVALID_KEY"}},
        "output": {"utilization_format": "percent_1dp"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(firm_yaml, f)
        firm_path = f.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"limits": {}}, f)
        base_path = f.name
    with pytest.raises(ValidationError):
        load_config(base_path, firm_path)
