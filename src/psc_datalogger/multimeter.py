import logging
import time
from abc import ABC, abstractmethod

from pyvisa.resources import SerialInstrument


class InvalidNplcException(Exception):
    """Exception thrown when user attempts to input an NPLC value that is
    not valid for one-or-more multimeters"""

    min_allowed: float
    max_allowed: float

    def __init__(self, min_allowed: float, max_allowed: float, *args):
        self.min_allowed = min_allowed
        self.max_allowed = max_allowed
        super().__init__(args)


class Multimeter(ABC):
    """Generic type of Multimeters. Provides interface for possible operations
    on different controllers"""

    # The minimum and maximum valid NPLC values.
    nplc_min = None
    nplc_max = None

    def __init__(self):
        if self.nplc_min is None or self.nplc_max is None:
            raise NotImplementedError(
                "Subclasses must define nplc_min and nplc_max attributes"
            )

    @abstractmethod
    def initialize(self, connection: SerialInstrument):
        """Perform the commands to  initialize (or reset) the multimeter to a
        known state"""

    @abstractmethod
    def set_nplc(self, connection: SerialInstrument, nplc: int):
        """Perform the commands to set the given nplc. Raises InvalidNplcException if
        nplc is invalid."""

    @abstractmethod
    def take_reading(self, connection: SerialInstrument) -> str:
        """Perform the commands to return a single voltage reading"""


class Agilent3458A(Multimeter):
    """Implements the required commands for an Agilent 3458A multimeter"""

    nplc_min = 1
    nplc_max = 2000

    def initialize(self, connection: SerialInstrument):
        self._ensure_prologix_settings(connection)
        connection.write("PRESET NORM")  # Set a variety of defaults
        connection.write("BEEP 0")  # Disable annoying beeps

        # This means the instrument will stop collecting measurements, thus
        # not filling its internal memory buffer. Later we will send single
        # trigger events and immediately read it, thus keeping the buffer
        # empty so we avoid reading stale results
        connection.write("TRIG HOLD")

        logging.info("Initialized Agilent3458A")

    def set_nplc(self, connection: SerialInstrument, nplc: int):
        self._ensure_prologix_settings(connection)
        if not self.nplc_min <= nplc <= self.nplc_max:
            raise InvalidNplcException(self.nplc_min, self.nplc_max)

        connection.write(f"NPLC {nplc}")

    def take_reading(self, connection: SerialInstrument) -> str:
        # Send single trigger command to the multimeter, and return the resultant value
        raw = connection.query("TRIG SGL")
        return self._clean_string(raw)

    def _clean_string(self, volts: str) -> str:
        """Clean up the returned string by removing extraneous characters"""
        # Value format is e.g. " 9.089320482E+00\r\n"
        # Occasionally there are also leading NULL bytes.
        return volts.replace("\x00", "").strip(" \r\n")

    def _ensure_prologix_settings(self, connection: SerialInstrument):
        connection.write("++auto 1")  # Enables use of "query"
        connection.read_termination = "\r\n"


class Agilent34401A(Multimeter):
    """Implements the required commands for an Agilent 34401A multimeter"""

    nplc_min = 0.02
    nplc_max = 100

    def initialize(self, connection: SerialInstrument):
        self._ensure_prologix_settings(connection)
        connection.write("*RST")  # Reset the multimeter to its power-on configuration.
        # Configure for voltage reading with range of 10V, resolution of 0.003
        connection.write("CONFigure:VOLTage:DC 10, 0.003")
        connection.write("SYSTEM:BEEPER:STATE OFF")  # Disable system beeps

        logging.info("Initialized Agilent34401A")

    def set_nplc(self, connection: SerialInstrument, nplc: int):
        self._ensure_prologix_settings(connection)

        if not self.nplc_min <= nplc <= self.nplc_max:
            raise InvalidNplcException(self.nplc_min, self.nplc_max)

        connection.write(f"VOLT:DC:NPLCYCLES {nplc}")

    def take_reading(self, connection: SerialInstrument) -> str:
        self._ensure_prologix_settings(connection)

        # Get the currently configured NPLC setting, to allow us to estimate how
        # long the subsequent voltage reading will take
        connection.write("VOLT:DC:NPLCYCLES?")
        nplc = connection.query("++read eoi")

        nplc_float = float(self._clean_string(nplc))

        assert self.nplc_min <= nplc_float <= self.nplc_max, "Invalid NPLC read"

        # Triggers a single reading of the multimeter, which will save the data
        # into internal memory. This can take several seconds, based on NPLC setting.
        connection.write("INIT")

        # Estimate how long to wait. An NPLC of 50 should take 1 second (matches
        # electrical frequency). Add 1 for some padding.
        wait_time = (nplc_float / 50) + 1
        time.sleep(wait_time)

        # Data should now be in internal memory; tell the multimeter to move it
        # to output buffer, then tell the Prologix controller to read it.
        connection.write("FETCH?")
        volts = connection.query("++read eoi")

        return self._clean_string(volts)

    def _clean_string(self, volts: str) -> str:
        """Clean up the returned string by removing extraneous characters"""
        return volts.replace("\x00", "")

    def _ensure_prologix_settings(self, connection: SerialInstrument):
        # "auto 1" causes "error -420 Query Unterminated" errors when doing write
        # commands that don't return any data, so must do manual explicit write and read
        connection.write("++auto 0")
        connection.read_termination = "\n"
