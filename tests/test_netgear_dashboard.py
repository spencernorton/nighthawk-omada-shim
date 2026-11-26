"""Real, field-limited RS700S 1.0.11.8 labels; the packet counts and private settings are omitted."""

from email.message import Message
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock

import pytest

from open_omada_device_agent.adapters.outbound.netgear.dashboard import (
    OVERVIEW,
    STATISTICS,
    DashboardStatus,
    PanelError,
    PhysicalLink,
    ReadSession,
    RejectedCredential,
    StockDashboard,
    channel,
    parse_dashboard,
)


def read_fixture(n):
    return (
        Path(__file__).parent / "fixtures" / "netgear-dashboard" / f"router{n}.html"
    ).read_text()


@pytest.mark.parametrize(
    ("n", "channels", "speed"),
    [(1, {"2G": 1, "5G": 100, "6G": 69}, 10000), (2, {"2G": 7, "5G": 40, "6G": 69}, 2500)],
)
def test_real_fields(n, channels, speed):
    page = read_fixture(n)
    assert parse_dashboard(page, page, "WAN") == DashboardStatus(
        channels, PhysicalLink(True, speed, True)
    )
    assert parse_dashboard(page, page, "LAN4").uplink == (
        PhysicalLink(True, 100, False) if n == 1 else PhysicalLink(False, 0, None)
    )
    assert parse_dashboard(page, page, "LAN 10G").uplink == (
        PhysicalLink(True, 2500, True) if n == 1 else PhysicalLink(False, 0, None)
    )


@pytest.mark.parametrize(
    "bad",
    [
        "Auto",
        "Auto ()",
        "Auto (36 + 40)",
        "Auto (36(P) + 40(P))",
        "Auto (36(P) + 36)",
        "Auto (36(Q))",
        "0",
        "533",
    ],
)
def test_unresolved_or_ambiguous_channel(bad):
    assert channel(bad, "5G") is None


def test_status_fields_fail_independently():
    page = read_fixture(2)
    assert parse_dashboard(page, "", "WAN").uplink is None
    assert parse_dashboard("", page, "WAN").channels == {}
    assert parse_dashboard(page, page.replace("Tx B/s", "Rx B/s"), "WAN").uplink is None
    assert parse_dashboard(page, page.replace(">LAN1<", ">WAN<"), "WAN").uplink is None
    assert parse_dashboard(page.replace(">Auto (7)<", ">Auto<"), page, "WAN").channels == {
        "5G": 40,
        "6G": 69,
    }
    with pytest.raises(PanelError):
        parse_dashboard("login", "login", "WAN")


def response(status, body="", **headers):
    fields = Message()
    for key, value in headers.items():
        fields[key.replace("_", "-")] = value
    return status, fields, body.encode()


def new_reader():
    return ReadSession("192.0.2.100", "34" * 32, "operator", "test-secret")


def test_challenge_once_scope_session_and_refresh(monkeypatch):
    reader = new_reader()
    seen = []
    replies = iter(
        [
            response(401, WWW_Authenticate='Basic realm="router"'),
            response(200, 'top.location.replace("start.htm")'),
            response(200, "Home"),
            response(200, "radio"),
            response(200, "stats"),
            response(200, "radio"),
            response(200, "stats"),
        ]
    )

    def exchange(path, referrer):
        seen.append((path, reader.challenged))
        return next(replies)

    monkeypatch.setattr(reader, "_exchange", exchange)
    assert reader.read() == reader.read() == ("radio", "stats")
    assert seen == [
        ("/", False),
        ("/", True),
        ("/start.htm", True),
        (OVERVIEW, True),
        (STATISTICS, True),
        (OVERVIEW, True),
        (STATISTICS, True),
    ]


@pytest.mark.parametrize(
    "target", ["https://example.invalid/start.htm", "http://192.0.2.100/start.htm", "/apply.cgi"]
)
def test_refuse_untrusted_redirect(monkeypatch, target):
    reader = new_reader()
    exchange = MagicMock(return_value=response(302, Location=target))
    monkeypatch.setattr(reader, "_exchange", exchange)
    with pytest.raises(PanelError):
        reader.read()
    exchange.assert_called_once()


def test_certificate_and_path_checked_before_credentials(monkeypatch):
    reader = new_reader()
    transport = MagicMock()
    transport.sock.getpeercert.return_value = b"wrong-device"
    monkeypatch.setattr("http.client.HTTPSConnection", lambda *a, **kw: transport)
    with pytest.raises(PanelError):
        reader.read()
    for path in ("/logout.htm", "/apply.cgi"):
        with pytest.raises(PanelError):
            reader.get(path)
    transport.connect.assert_called_once()
    transport.request.assert_not_called()
    transport.close.assert_called_once()


def test_bad_credential_rejected_after_one_challenge(monkeypatch):
    reader = new_reader()
    exchange = MagicMock(return_value=response(401, WWW_Authenticate='Basic realm="router"'))
    monkeypatch.setattr(reader, "_exchange", exchange)
    with pytest.raises(RejectedCredential):
        reader.read()
    assert exchange.call_count == 2


def test_async_single_flight_cache_expiry_and_error_backoff():
    clock = [1000.0]
    gate = Event()
    entered = Event()
    page = read_fixture(2)

    def delayed_sample():
        entered.set()
        assert gate.wait(2)
        return page, page

    session = MagicMock()
    session.read.side_effect = delayed_sample
    provider = StockDashboard(lambda: session, "WAN", now=lambda: clock[0])
    assert provider.latest() is None and entered.wait(2)
    thread = provider._worker
    assert provider.latest() is None and session.read.call_count == 1
    gate.set()
    thread.join(2)
    assert provider.latest().uplink.mbps == 2500
    clock[0] += StockDashboard.REFRESH
    gate.clear()
    entered.clear()

    def fail():
        entered.set()
        assert gate.wait(2)
        raise OSError("fixture")

    session.read.side_effect = fail
    assert provider.latest().uplink.mbps == 2500 and entered.wait(2)
    thread = provider._worker
    gate.set()
    thread.join(2)
    clock[0] = 1000 + StockDashboard.MAX_AGE
    assert provider.latest() is None and session.read.call_count == 2
    clock[0] = 1000 + StockDashboard.REFRESH + StockDashboard.BACKOFF - 1
    assert provider.latest() is None and session.read.call_count == 2


def test_bad_credential_suspends_background_reader_indefinitely(caplog):
    clock = [1000.0]
    session = MagicMock()
    session.read.side_effect = RejectedCredential("test-secret")
    provider = StockDashboard(lambda: session, "WAN", now=lambda: clock[0])
    provider._refresh()
    clock[0] += 30 * 24 * 3600
    assert provider.latest() is None and session.read.call_count == 1
    assert "test-secret" not in caplog.text


def test_runtime_reports_the_selected_physical_jack_and_preserves_configured_fallback(
    monkeypatch, tmp_path
):
    from dataclasses import replace
    from open_omada_device_agent.bootstrap.runtime import build_runtime
    from open_omada_device_agent.bootstrap.settings import AgentSettings

    snapshot = [None]
    calls = []

    class Source:
        def __init__(self, factory, jack):
            calls.append(jack)

        def latest(self):
            return snapshot[0]

    monkeypatch.setattr("open_omada_device_agent.bootstrap.runtime.StockDashboard", Source)
    base = replace(
        AgentSettings.from_environment(),
        southbound="netgear",
        netgear_host="192.0.2.25",
        netgear_password="fixture",
        netgear_dashboard_cert_sha256="ab" * 32,
        netgear_dashboard_uplink="LAN4",
        lan_rate=10000.0,
        lan_duplex=1,
        state_file=tmp_path / "state",
        netgear_beacon_file=None,
        netgear_secondary_beacon_file=None,
    )
    inform = build_runtime(base).inform
    monkeypatch.setattr(inform, "_device_info", lambda: {"upTime": 30})
    monkeypatch.setattr(inform, "_clients", lambda: ())
    monkeypatch.setattr(
        inform._wireless_projection, "wireless", lambda: {"wSettings_5G": {"ch": "0"}}
    )
    observed_bytes = {"port": "LAN", "rx": 123, "tx": 456}
    monkeypatch.setattr(inform, "_uplink_traffic", lambda port, up: observed_bytes)

    def get():
        body = inform.build(need_reply=False, uptime=30)
        assert body["lanTraffic"] is observed_bytes
        return body["lanInfo"], body["uplinkPortStatus"][0], body["wSettings_5G"]["ch"]

    assert calls == ["LAN4"]
    cfg, port, channel = get()
    assert (cfg["rate"], port["speed"], channel) == ("10000", 10000, "0")
    for link, speed, duplex in [
        (PhysicalLink(True, 2500, True), 2500, 2),
        (PhysicalLink(True, 100, False), 100, 1),
        (PhysicalLink(False, 0, None), 0, 0),
    ]:
        snapshot[0] = DashboardStatus({"5G": 40}, link)
        lan, port, ch = get()
        assert lan == {"rate": str(speed), "duplex": duplex, "port": "LAN"}
        assert (port["speed"], port["duplex"], port["link"], ch) == (
            speed,
            duplex,
            int(link.up),
            "40",
        )
    snapshot[0] = DashboardStatus({}, None)
    assert get()[0] == cfg
    legacy = build_runtime(replace(base, netgear_dashboard_cert_sha256="")).inform
    assert calls == ["LAN4"] and not callable(legacy._lan)
