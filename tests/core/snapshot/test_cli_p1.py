from click.testing import CliRunner
import pytest

from src.cli.core_collect import cli


def test_p1_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["enrich-corpus-fields", "--help"])
    assert res.exit_code == 0
    assert "Stream the OpenAlex snapshot" in res.output or "fill" in res.output.lower()
