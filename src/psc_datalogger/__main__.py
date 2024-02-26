from argparse import ArgumentParser

from . import __version__
from .gui import application

__all__ = ["main"]


def main(args=None):
    parser = ArgumentParser()
    parser.add_argument("-v", "--version", action="version", version=__version__)
    args = parser.parse_args(args)

    application()


# test with: python -m psc_datalogger
if __name__ == "__main__":
    main()
