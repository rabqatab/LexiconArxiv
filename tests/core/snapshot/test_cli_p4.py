from click.testing import CliRunner

from src.cli.core_collect import cli


def test_p4_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["extend-cited-by-from-snapshot", "--help"])
    assert res.exit_code == 0
    assert "max-citers-per-paper" in res.output
