import pytest

from open_omada_device_agent import __version__
from open_omada_device_agent.cli import build_parser


def test_runtime_and_cli_version_match_release(capsys):
    assert __version__ == "0.9.1"

    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == "open-omada-agent 0.9.1\n"
