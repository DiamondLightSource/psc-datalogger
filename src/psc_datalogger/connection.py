import logging
import time
from collections import OrderedDict
from csv import DictWriter
from dataclasses import dataclass
from datetime import datetime
from threading import Event, RLock
from typing import List, Optional, TextIO, Tuple, Type, cast

import pyvisa
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QLineEdit
from pyvisa.resources import Resource, SerialInstrument

from .multimeter import Agilent3458A, InvalidNplcException, Multimeter
from .statusbar import StatusBar
from .temperature.converter import volts_to_celcius


class ConnectionManager:
    """Manage the connection to the instruments, which is handled on a separate
    thread."""

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
        self._worker.clear_status.connect(status_bar.clear_status)

    def set_nplc_input(self, nplc_input: QLineEdit):
        """Save the GUI component that houses the NPLC value"""
        self._worker.nplc_input = nplc_input

    def set_interval(self, interval: str):
        """Set the update interval for the logging thread"""
        if interval != "":  # Empty string passed if the textbox is cleared
            self._worker.interval = float(interval)

    def set_filepath(self, filepath):
        """Set the filepath for the logging thread"""
        self._worker.set_filepath(filepath)

    def set_instrument(
        self,
        instrument_number: int,
        enabled: bool,
        gpib_address: str,
        measure_temp: bool,
        multimeter_type: Type[Multimeter],
    ) -> None:
        """Configure the given instrument number with the provided parameters"""
        try:
            self._worker.set_instrument(
                instrument_number, enabled, gpib_address, measure_temp, multimeter_type
            )
        except ConnectionNotInitialized:
            logging.exception(
                f"Could not set instrument {instrument_number}, parmameters: "
                f"enabled {enabled} address {gpib_address} measure_temp {measure_temp}"
            )

    def set_nplc(self, nplc: str) -> None:
        """Configure the NPLC value for all instruments"""
        try:
            self._worker.set_nplc(nplc)
        except ConnectionNotInitialized:
            logging.exception(f"Could not set NPLC to {nplc}")

    def start_logging(self) -> bool:
        """Start the logging process in the background thread.
        Returns True if logging successfully started, else False"""
        if self._worker.validate_parameters():
            self.logging_signal.set()
            self.status_bar.logging_started()
            return True
        else:
            return False

    def stop_logging(self) -> None:
        """Stop the logging process in the background thread"""
        self.logging_signal.clear()
        self.status_bar.logging_stopped()


@dataclass
class InstrumentConfig:
    """Contains the configuration for a single instrument"""

    # Whether this instrument is marked enabled in the GUI
    enabled: bool = False
    # GPIB address of instrument
    address: int = -1
    # Indicate whether the voltage read should be converted into a temperature
    convert_to_temp: bool = False
    # The multimeter in use. Default to 3458A, matching the GUI's default
    multimeter: Multimeter = Agilent3458A()


class DataWriter(DictWriter):
    """Class that handles writing data to a file"""

    file: TextIO

    csv_fieldnames = [
        "timestamp",
        "instrument 1",
        "instrument 2",
        "instrument 3",
    ]

    def __init__(self, filepath: str):
        self.file = open(filepath, "w", newline="")

        super().__init__(self.file, fieldnames=self.csv_fieldnames, dialect="excel")

        self.writeheader()
        self.file.flush()

    def close(self) -> None:
        self.file.close()

    def write(self, timestamp: datetime, ins_1: str, ins_2: str, ins_3: str):
        """Write the given data to the file"""
        len_written = self.writerow(
            {
                self.csv_fieldnames[0]: str(timestamp),
                self.csv_fieldnames[1]: ins_1,
                self.csv_fieldnames[2]: ins_2,
                self.csv_fieldnames[3]: ins_3,
            }
        )
        logging.debug(f"DictWriter wrote {len_written} bytes")

        self.file.flush()
        logging.debug("File flushed")


class PrologixNotFoundException(Exception):
    """Exception thrown when the Prologix controller is not found"""


class ConnectionNotInitialized(Exception):
    """Exception thrown when attempting to access the serial connection when
    it has not yet been initialized."""


class Worker(QObject):
    """Class that does the serial connection to the instruments

    NOTE: This expects to be run in a separate QThread from the main GUI"""

    # Signal that initialization has completed
    init_complete = pyqtSignal()

    # Signal that we have queried all the instruments.
    # Parameter is the timestamp this occurred at.
    query_complete = pyqtSignal(datetime)

    # Signal that an error has occurred. Parameter is the error message.
    error = pyqtSignal(str)

    # Signal that will clear the status bar of any text.
    # Used to clear it after errors occur.
    clear_status = pyqtSignal()

    # The update interval that readings should be taken at
    interval: float = 0  # seconds

    writer: Optional[DataWriter] = None

    # Keep track of the configuration of each of the 3 possible devices
    # Ordered dict to ensure that we always read instruments in order when iterating
    instrument_configs = OrderedDict(
        {1: InstrumentConfig(), 2: InstrumentConfig(), 3: InstrumentConfig()}
    )

    # The connection to the Prologix controller. Do not directly access, use the
    # _connection_* wrapper functions.
    _connection: SerialInstrument

    # Constant to mark a measurement could not be taken. Also written to results file.
    ERROR_STRING = "#ERROR"

    # The GUI widget that contains the NPLC value
    nplc_input: QLineEdit

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

        self.running = True

    def set_filepath(self, filepath: str):
        """Create the writer for the given filepath. Closes any existing
        writer/filehandle."""
        logging.info(f"Setting filepath to {filepath}")
        with self.lock:
            if self.writer:
                self.writer.close()

            self.writer = DataWriter(filepath)

    def set_instrument(
        self,
        instrument_number: int,
        enabled: bool,
        gpib_address: str,
        measure_temp: bool,
        multimeter_type: Type[Multimeter],
    ) -> None:
        """Configure the given instrument number with the provided parameters"""
        assert (
            1 <= instrument_number <= 3
        ), f"Invalid instrument number {instrument_number}"

        try:
            address = int(gpib_address)
        except ValueError:
            # May not be an address set in the GUI; this happens when the "enable"
            # tickbox is first pressed and the address field is likely empty.
            logging.info(f"gpib address '{gpib_address}' invalid")
            address = -1

        logging.info(
            f"Configuring instrument {instrument_number}; Enabled {enabled},"
            f"Address {gpib_address}, measure temp {measure_temp}"
        )
        self.instrument_configs[instrument_number] = InstrumentConfig(
            enabled, address, measure_temp, multimeter_type()
        )

        self._init_instrument(self.instrument_configs[instrument_number])

    def _init_instrument(self, instrument: InstrumentConfig) -> None:
        """Initialize the given instrument"""
        logging.debug(f"Initializing instrument at address {instrument.address}")

        if not instrument.enabled:
            logging.debug(
                f"Skipping _init_instrument for instrument {instrument.address}"
            )
            return

        gpib_address = instrument.address

        if gpib_address <= 0:
            raise ValueError(
                f"_init_instrument called with invalid address '{gpib_address}'"
            )

        multimeter = instrument.multimeter

        with self.lock:
            self._set_prologix_address(gpib_address)

            multimeter.initialize(self._connection)

            self._set_nplc(instrument, int(self.nplc_input.text()))

            # Read all data remaining in the buffer; it is possible for
            # samples to be taken while initializing the multimeters.
            # (Mostly an issue with the 3458A but doesn't hurt for other types)
            while self._connection_bytes_in_buffer():
                try:
                    self._connection_read()
                except pyvisa.VisaIOError:
                    logging.debug(f"Instrument {gpib_address} data buffer emptied")

        logging.debug(f"Instrument initialized at address {instrument.address}")

    def set_nplc(self, nplc: str) -> None:
        """Set the NPLC for all configured instruments"""

        try:
            int_plc = int(nplc)
        except ValueError:
            # This happens if the input text box is empty
            return

        try:
            for instrument in self.instrument_configs.values():
                if instrument.enabled:
                    self._set_nplc(instrument, int_plc)
        except InvalidNplcException as e:
            self.error.emit(
                f"NPLC value {int_plc} outside allowed range "
                f"{e.min_allowed} - {e.max_allowed}"
            )
            return

        # Assuming all devices accepted the NPLC, clear any errors
        self.clear_status.emit()

    def _set_nplc(self, instrument: InstrumentConfig, nplc: int) -> None:
        """Set the NPLC for the given instrument"""
        with self.lock:
            self._set_prologix_address(instrument.address)

            multimeter = instrument.multimeter

            multimeter.set_nplc(self._connection, nplc)

            # The number of samples is tied to the electrical frequency.
            # i.e. an NPLC of 50 will take 1 second, as our mains runs at 50Hz.
            # So we need to ensure our timeout is more-than-enough to cover it
            # However we want to ensure we always have at least a 5 second timeout
            # as even the smallest NPLC values seem to take a few seconds to complete
            timeout = max(5000, nplc * 100)
            self._set_connection_timeout(timeout)  # ms

    def _set_prologix_address(self, gpib_address: int) -> None:
        """Configure the Prologix to point to the given GPIB address"""
        with self.lock:
            self._connection_write(f"++addr {gpib_address}")
            # Prologix seems to need a moment to process previous command
            time.sleep(0.1)

    def validate_parameters(self) -> bool:
        """Returns True if all required parameters are set, otherwise False"""

        if all(x.address <= 0 for x in self.instrument_configs.values()):
            logging.warning("No GPIB addresses set for any instrument")
            return False

        if self.interval <= 0:
            logging.warning("No update interval set")
            return False

        if self.writer is None:
            logging.warning("No logfile selected")
            return False

        if self.nplc_input.text() == "":
            logging.warning("No NPLC value set")
            return False

        logging.info("Parameters are valid")
        return True

    def run(self):
        """Main work function of this class. Initializes a connection then continually
        queries the instruments for data, and logs it"""

        while True:
            try:
                self.init_connection()
                self.init_complete.emit()
                break
            except PrologixNotFoundException:
                errmsg = "Prologix controller not found. Trying again in 5 seconds"
                logging.exception(errmsg)
                self.error.emit(errmsg)
                time.sleep(5)

        while self.running:
            self.logging_signal.wait()

            logging.debug("Starting log loop")

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
            logging.debug("Log sleep finished")

    def init_connection(self):
        """Initialize the connection to the Prologix device"""
        with self.lock:
            rm = pyvisa.ResourceManager()

            resources = rm.list_resources()

            logging.info(f"Resources available: {resources}")

            # Find the connection that is the Prologix controller
            # Reversed as it's more common for it to be the last resource in the list
            for resource in reversed(resources):
                conn = rm.open_resource(resource)
                if self._check_resource_is_prologix(conn):
                    logging.info(f"Found Prologix controller at {resource}")
                    break
            else:
                rm.close()
                errmsg = "No Prologix controller found"
                logging.error(errmsg)
                raise PrologixNotFoundException(errmsg)

            # The open_resource function returns a very generic type
            self._connection = cast(SerialInstrument, conn)

            logging.info("Connection initialized")

    def _check_resource_is_prologix(self, resource: Resource) -> bool:
        """Returns True if the given Resource is a Prologix controller, otherwise
        False"""
        try:
            assert isinstance(resource, SerialInstrument)
            # We assume that only a Prologix controller will respond to ++help
            help_str = resource.query("++help")
            if help_str:
                return True
        except pyvisa.VisaIOError:
            # Timeout; probably not the right device!
            logging.debug(f"No response to ++help for resource {resource}")
            return False
        except AssertionError:
            # Not a SerialInstrument, definitely not the correct resource
            logging.debug(f"Resource {resource} is not a SerialInstrument")
            return False

        return False

    def do_logging(self):
        """Take one set of readings and write them to file"""

        with self.lock:
            self._connection_check()
            assert self.writer is not None

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

            self.writer.write(
                timestamp=results[0],
                ins_1=results[1],
                ins_2=results[2],
                ins_3=results[3],
            )

    def query_instruments(self) -> Tuple[datetime, str, str, str]:
        """Query the instruments and return the timestamp followed by three instrument
        readings."""

        with self.lock:
            measurement_time = datetime.now()

            measurements: List[str] = []
            for i in self.instrument_configs.values():
                logging.debug(f"Querying instrument {i.address}")
                if i.address <= 0:
                    # No address, add empty entry
                    measurements.append("")
                    continue

                try:
                    # Configure Prologix to talk to the current device
                    self._connection_write(f"++addr {i.address}")

                    logging.debug(f"Triggering instrument {i.address}")

                    multimeter = i.multimeter

                    # Request a single measurement
                    val = multimeter.take_reading(self._connection)

                    logging.debug(f"Address {i.address} Value {val}")

                except Exception:
                    # Issue reading from this instrument. Mark an error but continue
                    # processing other instruments
                    logging.exception(f"Exception reading from address {i.address}")
                    val = self.ERROR_STRING
                else:
                    try:
                        if i.convert_to_temp:
                            val = str(volts_to_celcius(val))
                    except AssertionError:
                        # Issue converting value to temperature. Mark an error but
                        # continue processing other instruments
                        logging.exception(
                            f"Exception converting value {val} to "
                            f"temperature from address {i.address}"
                        )
                        val = self.ERROR_STRING

                measurements.append(val)

            assert len(measurements) == 3
            measurement_tuple = cast(Tuple[str, str, str], tuple(measurements))
            return measurement_time, *measurement_tuple

    def _exit(self) -> None:
        """Cleanly stop the run() method to terminate all processing.
        This method is only used in testing!"""
        if self.writer:
            self.writer.close()
        # Send relevant flags to allow run() to terminate
        # Note it will do 1 more iteration of the loop, including the sleep
        self.running = False
        self.logging_signal.set()

    def _connection_check(self) -> None:
        """Check whether connection is initialized.

        Mostly required to guard against potential checks before the Prologix
        controller has connected (or maybe there isn't even one plugged in yet!)"""
        if not hasattr(self, "_connection"):
            logging.warning(
                "Attempted to write to connection when it was not initialized"
            )
            raise ConnectionNotInitialized()

    def _connection_write(self, command: str) -> None:
        """Write the given command to the connection"""
        self._connection_check()
        self._connection.write(command)

    def _connection_bytes_in_buffer(self) -> int:
        """Access connection.bytes_in_buffer"""
        self._connection_check()
        return self._connection.bytes_in_buffer

    def _connection_read(self) -> str:
        """Read data from the connection"""
        self._connection_check()
        return self._connection.read()

    def _set_connection_timeout(self, timeout: int) -> None:
        """Set timeout on the connection.

        Timeout is in milliseconds."""
        self._connection_check()
        self._connection.timeout = timeout

    def _connection_query(self, command: str) -> str:
        """Write the given command to the connection and read the result"""
        self._connection_check()
        return self._connection.query(command)
