from click.testing import CliRunner

from src.cli.core_collect import cli


def test_snapshot_live_delta_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["snapshot-live-delta", "--help"])
    assert res.exit_code == 0
    for opt in ("--days-back", "--since", "--dry-run", "--max-injections"):
        assert opt in res.output, f"missing option {opt}"
