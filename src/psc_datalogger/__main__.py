import logging
from argparse import ArgumentParser

from . import __version__
from .gui import application

__all__ = ["main"]


def main(args=None):
    parser = ArgumentParser()
    parser.add_argument("-v", "--version", action="version", version=__version__)
    parser.add_argument(
        "-l",
        "--log",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
        default="WARNING",
    )
    args = parser.parse_args(args)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s:%(levelname)s:%(name)s:%(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    application()


# test with: python -m psc_datalogger
if __name__ == "__main__":
    main()
