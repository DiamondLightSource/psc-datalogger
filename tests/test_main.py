import logging
import subprocess
import sys

import pytest

from psc_datalogger import __version__
from psc_datalogger.__main__ import parse_args


def test_cli_version():
    cmd = [sys.executable, "-m", "psc_datalogger", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__


def test_cli_script_entrypoint_version():
    """Check that the entrypoint defined in [project.scripts] inside
    pyproject.toml works"""
    cmd = ["psc-datalogger", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__


@pytest.mark.parametrize(
    "level_str, level_const",
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_parse_log_level(level_str, level_const):
    args = parse_args(["-l", level_str])
    assert args.log_level == level_const
