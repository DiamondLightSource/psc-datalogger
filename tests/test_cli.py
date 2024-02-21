import subprocess
import sys

from psc_datalogger import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "psc_datalogger", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
