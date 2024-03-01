import logging
import time
from collections import OrderedDict
from csv import DictWriter
from dataclasses import dataclass
from datetime import datetime
from threading import Event, RLock
from typing import Optional, TextIO, Tuple

import pyvisa
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from .statusbar import StatusBar
from .thermocouple.thermocouple import volts_to_celcius


class ConnectionManager:
    """Manage the connection to the instruments
    NOTE: There is expected to only be 1 Prologix device connected, which
    will talk to up to 3 Agilent3458A Multimeters"""

    def __init__(self):
        self.thread = QThread()
        # Use "signal" as "event" is used by PyQt
        self.logging_signal = Event()
        self._worker = Worker(self.logging_signal)
        self._worker.moveToThread(self.thread)
        self.thread.started.connect(self._worker.run)

    def start(self):
        """Begin the worker thread"""
        logging.debug("Starting worker thread")
        self.thread.start()

    def set_status_bar(self, status_bar: StatusBar):
        """Set up the status bar to display relevant information"""
        self.status_bar = status_bar
        self._worker.query_complete.connect(status_bar.query_complete_callback)
        self._worker.init_complete.connect(status_bar.init_complete_callback)
        self._worker.error.connect(status_bar.error_callback)

    def set_interval(self, interval: str):
        """Set the update interval for the logging thread"""
        self._worker.interval = float(interval)

    def set_filepath(self, filepath):
        """Set the filepath for the logging thread"""
        self._worker.set_filepath(filepath)

    def set_instrument(
        self, instrument_number: int, gpib_address: str, measure_temp: bool
    ):
        """Configure the given instrument number with the provided parameters"""
        self._worker.set_instruments(instrument_number, gpib_address, measure_temp)

    def start_logging(self) -> bool:
        """Start the logging process in the background thread"""
        if self._worker.validate_parameters():
            self.logging_signal.set()
            self.status_bar.logging_started()
            return True
        else:
            return False

    def stop_logging(self):
        """Stop the logging process in the background thread"""
        self.logging_signal.clear()
        self.status_bar.logging_stopped()


@dataclass
class InstrumentConfig:
    """Contains the configuration for a single instrument"""

    # GPIB address of instrument
    address: str = ""
    # Indicate whether the voltage read should be converted into a temperature
    measure_temp: bool = False


class Worker(QObject):
    """Class that does the serial connection to the instruments
    NOTE: This expects to be run in a separate QThread from the main GUI"""

    # Signal that initialization has completed
    init_complete = pyqtSignal()
    # Signal that we have queried all the instruments.
    # Parameter is the timestamp this occurred at.
    query_complete = pyqtSignal(datetime)

    # An error has occurred. Parameter is the error message.
    error = pyqtSignal(str)

    # The update interval that readings should be taken at
    interval: float = 0  # seconds

    csv_file: Optional[TextIO] = None
    csv_writer: Optional[DictWriter] = None

    # Keep track of the addresses of each of the 3 possible devices
    # Ordered dict to ensure that we always read instruments in order when iterating
    instrument_addresses = OrderedDict(
        {1: InstrumentConfig(), 2: InstrumentConfig(), 3: InstrumentConfig()}
    )

    connection: pyvisa.resources.SerialInstrument

    # Constant to mark a measurement could not be taken. Also written to results file.
    ERROR_STRING = "#ERROR"

    def __init__(self, logging_signal: Event):
        """
        Create a Worker instance.

        Args:
            logging_signal: An Event object that, when set, means logging should run
        """
        super().__init__()
        self.logging_signal = logging_signal

        # This lock protects both the file and the serial connection resources
        # Recursive to allow more defensive programming
        self.lock = RLock()

    def set_filepath(self, filepath):
        """Create the CSV writer for the given filepath. Closes any existing
        writer/filehandle."""
        logging.info(f"Setting filepath to {filepath}")
        with self.lock:
            if self.csv_writer:
                self.csv_writer = None
            if self.csv_file:
                self.csv_file.close()

            fieldnames = ["timestamp", "instrument 1", "instrument 2", "instrument 3"]
            self.csv_file = open(filepath, "w")

            self.csv_writer = DictWriter(
                self.csv_file, fieldnames=fieldnames, dialect="excel"
            )
            self.csv_writer.writeheader()
            self.csv_file.flush()

    def set_instruments(
        self, instrument_number: int, gpib_address: str, measure_temp: bool
    ) -> None:
        """Configure the given instrument number with the provided parameters"""

        logging.info(
            f"Configuring instrument {instrument_number}; Address {gpib_address},"
            f"measure temp {measure_temp}"
        )
        self.instrument_addresses[instrument_number] = InstrumentConfig(
            gpib_address, measure_temp
        )

        self._init_instrument(self.instrument_addresses[instrument_number])

    def _init_instrument(self, instrument: InstrumentConfig) -> None:
        """Initialize the given instrument"""
        logging.debug(f"Initializing instrument at address {instrument.address}")
        gpib_address = instrument.address
        with self.lock:
            if gpib_address != "":
                self.connection.write(f"++addr {gpib_address}")
                # Instruct Prologix to enable read-after-write,
                # which allows the controller to write data back to us!
                self.connection.write("++auto 1")

                time.sleep(0.1)  # Give Prologix a moment to process previous commands

                self.connection.write("PRESET NORM")  # Set a variety of defaults
                self.connection.write("BEEP 0")  # Disable annoying beeps
                # Clear all memory buffers and disable all triggering
                self.connection.write("CLEAR")

                self.connection.write("TRIG HOLD")  # Disable triggering
                # This means the instrument will stop collecting measurements, thus
                # not filling its internal memory buffer. Later we will send single
                # trigger events and immediately read it, thus keeping the buffer
                # empty so we avoid reading stale results

                # Finally, read all data remaining in the buffer; it is possible for
                # samples to be taken in the time between us sending the various above
                # commands
                while self.connection.bytes_in_buffer:
                    try:
                        self.connection.read()
                    except pyvisa.VisaIOError:
                        logging.debug(f"Instrument {gpib_address} data buffer emptied")

        logging.debug(f"Instrument initialized at address {instrument.address}")

    def validate_parameters(self) -> bool:
        """Returns True if all required parameters are set, otherwise False"""

        if all(x.address == "" for x in self.instrument_addresses.values()):
            logging.warning("No GPIB addresses set for any instrument")
            return False

        if self.interval == 0:
            logging.warning("No update interval set")
            return False

        if self.csv_file is None or self.csv_writer is None:
            logging.warning("No logfile selected")
            return False

        logging.info("Parameters are valid")
        return True

    def run(self):
        """Main work function of this class. Initializes a connection then continually
        queries the instruments for data, and logs it"""

        self.init_connection()
        self.init_complete.emit()

        while True:
            self.logging_signal.wait()

            try:
                self.do_logging()
            except Exception:
                # Ignore it and continue working
                logging.exception("Unexpected exception while logging data")
                pass

            # Sleeping like this will cause minor drift over time, equal to how long
            # reading from all instruments takes. This becomes a major problem if
            # timeouts occur as they invoke a 3-second delay per timeout.
            time.sleep(self.interval)

    def init_connection(self):
        """Initialize the connection to the Prologix device"""
        with self.lock:
            logging.debug("Starting init_connection")
            rm = pyvisa.ResourceManager()

            logging.info(f"Resources available: {rm.list_resources()}")
            # TODO: Work out some way to make this dynamic...
            self.connection: pyvisa.resources.SerialInstrument = rm.open_resource(
                "ASRL/dev/ttyUSB0::INSTR"
            )  # type: ignore # The open_resource function returns a very generic type

            logging.info("Connection initialized")

    def do_logging(self):
        """Take one set of readings and write them to file"""

        with self.lock:
            assert self.connection is not None

            results = self.query_instruments()

            if any(x == self.ERROR_STRING for x in results):
                simple_timestamp = results[0].isoformat(sep=" ", timespec="seconds")
                logging.error("Unable to read data")
                self.error.emit(f"Unable to read data {simple_timestamp}")
            else:
                self.query_complete.emit(results[0])

            logging.info(
                f"Data read: {str(results[0])} {results[1]} {results[2]} {results[3]}"
            )

            if self.csv_writer and self.csv_file:
                self.csv_writer.writerow(
                    {
                        "timestamp": str(results[0]),
                        "instrument 1": results[1],
                        "instrument 2": results[2],
                        "instrument 3": results[3],
                    }
                )
                self.csv_file.flush()
                logging.debug("File flushed")

    def query_instruments(self) -> Tuple[datetime, str, str, str]:
        """Query the instruments and return the timestamp followed by three instrument
        readings."""

        with self.lock:
            measurement_time = datetime.now()

            measurements = []
            for i in self.instrument_addresses.values():
                if i.address == "":
                    # No address, add empty entry
                    measurements.append("")
                    continue

                try:
                    # Configure Prologix to talk to the current device
                    self.connection.write(f"++addr {i.address}")

                    logging.debug(f"Triggering instrument {i.address}")
                    # Request a single measurement
                    val: str = self.connection.query("TRIG SGL")

                    logging.debug(f"Address {i.address} Value {val}")

                    # Value format is e.g. " 9.089320482E+00\r\n"
                    # Occasionally there are leading NULL bytes.
                    val = val.strip(" \r\n").replace("\x00", "")
                except Exception:
                    # Issue reading from this instrument. Mark an error but continue
                    # processing other instruments
                    logging.exception(f"Exception reading from address {i.address}")
                    val = self.ERROR_STRING
                else:
                    try:
                        if i.measure_temp:
                            val = volts_to_celcius(val)
                    except AssertionError:
                        # Issue converting value to temperature. Mark an error but
                        # continue processing other instruments
                        logging.exception(
                            f"Exception converting value {val} to "
                            f"temperature from address {i.address}"
                        )
                        val = self.ERROR_STRING

                measurements.append(val)

            return measurement_time, *measurements
