import logging
import sys
from argparse import ArgumentParser, Namespace

# Note: It's important to use full package name here, otherwise Windows
# exe build tool can't find the module
from psc_datalogger import __version__
from psc_datalogger.gui import application

__all__ = ["main"]


def parse_args(args) -> Namespace:
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

    # Convert the textual log level into the logging module's equivalent constant
    args.log_level = getattr(logging, args.log_level)

    return args


def main():
    args = parse_args(sys.argv[1:])

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s:%(levelname)s:%(name)s:%(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    application()


# test with: python -m psc_datalogger
if __name__ == "__main__":
    main()
