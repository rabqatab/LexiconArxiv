from click.testing import CliRunner

from src.cli.core_collect import cli


def test_p3_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["discover-corpus-gaps", "--help"])
    assert res.exit_code == 0
    for opt in ("anchor-min-citers", "concept-min-recent", "concept-min-old",
                "concept-min-year", "max-injections"):
        assert opt in res.output, f"missing option {opt}"
