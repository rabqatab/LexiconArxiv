from click.testing import CliRunner

from src.cli.core_collect import cli


def test_embed_papers_consume_snapshot_queue_option():
    runner = CliRunner()
    res = runner.invoke(cli, ["embed-papers", "--help"])
    assert res.exit_code == 0
    assert "--consume-snapshot-queue" in res.output
