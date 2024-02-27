import time
import traceback
from collections import OrderedDict
from csv import DictWriter
from datetime import datetime
from threading import Event, RLock
from typing import Optional, TextIO, Tuple

import pyvisa
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from .statusbar import StatusBar


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

    def set_address(self, instrument_number: int, gpib_address: str):
        """Set the address for the given number instrument"""
        self._worker.set_address(instrument_number, gpib_address)

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

    # TODO: Add some validation to the incoming parameters, possibly in setters
    # The update interval that readings should be taken at
    interval: float = 0  # ms

    csv_file: Optional[TextIO] = None
    csv_writer: Optional[DictWriter] = None

    # Keep track of the addresses of each of the 3 possible devices
    # Ordered dict to ensure that we always read instruments in order when iterating
    instrument_addresses = OrderedDict({1: "", 2: "", 3: ""})

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
        print(f"Setting filepath to {filepath}")
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

    def set_address(self, instrument_number: int, gpib_address: str):
        """Set the address of the given instrument to the given address"""
        print("New address: ", instrument_number, gpib_address)

        with self.lock:
            if gpib_address != "":
                self.connection.write(f"++addr {gpib_address}")
                # Instruct Prologix to enable read-after-write,
                # which allows the controller to write data back to us!
                self.connection.write("++auto 1")

                time.sleep(0.1)  # Give Prologix a moment to process previous commands

                self.connection.write("PRESET")  # Set a variety of defaults
                self.connection.write("BEEP 0")  # Disable annoying beeps
                # Clear all memory buffers and disable all triggering
                self.connection.write("CLEAR")

                self.connection.write("TRIG HOLD")  # Disable triggering
                # This means the instrument will stop collecting measurements, thus not
                # filling its internal memory buffer. Later we will send single trigger
                # events and immediately read it, thus keeping the buffer empty so we
                # avoid reading stale results

            self.instrument_addresses[instrument_number] = gpib_address
            print("New dict:", self.instrument_addresses)

    def validate_parameters(self) -> bool:
        """Returns True if all required parameters are set, otherwise False"""

        if all(x == "" for x in self.instrument_addresses.values()):
            # No addresses set
            return False

        if self.interval == 0:
            # No interval set
            return False

        if self.csv_file is None or self.csv_writer is None:
            # No logfile set
            return False

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
            except Exception as e:
                # Ignore it so we try and continue next time
                # TODO: proper error reporting
                traceback.print_exc()
                self.error(f"Exception in run: {e}")
                pass

            time.sleep(self.interval / 1000.0)

    def init_connection(self):
        """Initialize the connection to the Prologix device"""
        # TODO: Set up proper logging!
        with self.lock:
            print("Starting init_connection")
            rm = pyvisa.ResourceManager()

            print(rm.list_resources())
            # TODO: Work out some way to make this dynamic...
            self.connection: pyvisa.resources.SerialInstrument = rm.open_resource(
                "ASRL/dev/ttyUSB0::INSTR"
            )  # type: ignore # The open_resource function returns a very generic type

    def do_logging(self):
        """Take one set of readings and write them to file"""

        with self.lock:
            print("Starting logging")

            assert self.connection is not None

            results = self.query_instruments()

            if any(x == self.ERROR_STRING for x in results):
                simple_timestamp = results[0].isoformat(sep=" ", timespec="seconds")
                self.error.emit(f"Unable to read data {simple_timestamp}")
            else:
                self.query_complete.emit(results[0])

            print(
                "Writing: ",
                {
                    "timestamp": str(results[0]),
                    "instrument 1": results[1],
                    "instrument 2": results[2],
                    "instrument 3": results[3],
                },
            )

            # In theory possible to have started logging before a file is set
            # TODO: Disable the "Start" button until the filepath is set?
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

    def query_instruments(self) -> Tuple[datetime, str, str, str]:
        """Query the instruments and return the timestamp followed by three instrument
        readings."""

        with self.lock:
            measurement_time = datetime.now()

            measurements = []
            for i in self.instrument_addresses.values():
                if i == "":
                    # No address, add empty entry
                    measurements.append("")
                    continue

                try:
                    # Configure Prologix to talk to the current device
                    self.connection.write(f"++addr {i}")

                    # Request a single measurement
                    val: str = self.connection.query("TRIG SGL")
                    # Value format is e.g. " 9.089320482E+00\r\n"
                    val = val.strip(" \r\n")
                except Exception:
                    # Issue reading from this instrument. Mark an error but continue
                    # processing other instruments
                    traceback.print_exc()
                    val = self.ERROR_STRING

                measurements.append(val)

            return measurement_time, *measurements
