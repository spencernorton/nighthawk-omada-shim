import json

from open_omada_device_agent import config
from open_omada_device_agent.ecsp import normalize_mac
from open_omada_device_agent.session_state import clear_state, load_state, save_state
from open_omada_device_agent.contexts.lifecycle.infrastructure.session_state import JsonSessionStateRepository
from open_omada_device_agent.contexts.lifecycle.domain import ManagedState


def test_managed_state_round_trip_does_not_persist_password(tmp_path):
    path = tmp_path / "state.json"
    saved = save_state(
        controller_id="0123456789abcdef0123456789abcdef",
        manage_port=29814,
        site_id="0123456789abcdef01234567",
        username="lab-user",
        config_version=7,
        sequence_id=9,
        path=path,
    )

    assert saved.mac == normalize_mac(config.MAC)
    loaded = load_state(path)
    assert loaded == saved
    raw = json.loads(path.read_text())
    assert raw["manage_port"] == 29814
    assert "password" not in raw
    assert "device_password" not in raw


def test_clear_managed_state(tmp_path):
    path = tmp_path / "state.json"
    save_state(
        controller_id="0123456789abcdef0123456789abcdef",
        manage_port=29814,
        path=path,
    )
    assert clear_state(path) is True
    assert load_state(path) is None
    assert clear_state(path) is False


def test_json_repository_implements_lifecycle_persistence_port(tmp_path):
    repository = JsonSessionStateRepository(
        tmp_path / "managed.json",
        device_mac=config.MAC,
        controller_host=config.CONTROLLER_HOST,
    )
    saved = repository.save(ManagedState(
        version=1,
        mac=normalize_mac(config.MAC),
        controller_host=config.CONTROLLER_HOST,
        controller_id="controller",
        manage_port=29814,
    ))

    assert repository.load() == saved
    assert repository.clear() is True
    assert repository.load() is None



def test_json_repository_ignores_stale_state_when_device_model_changes(tmp_path):
    state_file = tmp_path / "managed.json"
    eap110_repo = JsonSessionStateRepository(
        state_file,
        device_mac=config.MAC,
        controller_host="192.0.2.100",
        device_model="EAP110",
    )
    saved = eap110_repo.save(ManagedState(
        version=1,
        mac=normalize_mac(config.MAC),
        controller_host="192.0.2.100",
        controller_id="controller",
        manage_port=29814,
        model="EAP110",
    ))
    assert saved.model == "EAP110"
    assert eap110_repo.load() == saved

    # Switching model to EAP770 invalidates stale EAP110 reconnect state cleanly
    eap770_repo = JsonSessionStateRepository(
        state_file,
        device_mac=config.MAC,
        controller_host="192.0.2.100",
        device_model="EAP770",
    )
    assert eap770_repo.load() is None

    # Pre-0.3.0 state files without a stored "model" key remain readable on same-model upgrades
    raw = json.loads(state_file.read_text())
    raw.pop("model", None)
    state_file.write_text(json.dumps(raw))
    assert eap770_repo.load() is not None
