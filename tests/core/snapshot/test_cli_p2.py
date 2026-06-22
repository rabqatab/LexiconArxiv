from click.testing import CliRunner

from src.cli.core_collect import cli


def test_p2_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["resolve-stubs-from-snapshot", "--help"])
    assert res.exit_code == 0
    assert "allow-promotion" in res.output
    assert "allow-merge" in res.output
