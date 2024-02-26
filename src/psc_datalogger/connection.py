import time
import traceback
from collections import OrderedDict
from csv import DictWriter
from datetime import datetime
from threading import Event, RLock
from typing import Optional, TextIO

import pyvisa
from PyQt5.QtCore import QObject, QThread, pyqtSignal


class ConnectionManager:
    """Manage the connection to the instruments
    NOTE: There is expected to only be 1 Prologix device connected, which
    will talk to up to 3 Agilent3458A Multimeters"""

    work_requested = pyqtSignal(int)

    def __init__(self):
        self.thread = QThread()
        # Use "signal" as "event" is used by PyQt
        self.logging_signal = Event()
        self._worker = Worker(self.logging_signal)
        self._worker.moveToThread(self.thread)
        self.thread.started.connect(self._worker.run)
        self.thread.start()

    def set_interval(self, interval: str):
        """Set the update interval for the logging thread"""
        print("New interval: ", interval)
        self._worker.interval = interval

    def set_filepath(self, filepath):
        """Set the filepath for the logging thread"""
        self._worker.set_filepath(filepath)

    def set_address(self, instrument_number: int, gpib_address: str):
        """Set the address for the given number instrument"""
        self._worker.set_address(instrument_number, gpib_address)

    def start_logging(self):
        """Start the logging process in the background thread"""
        self.logging_signal.set()

    def stop_logging(self):
        """Stop the logging process in the background thread"""
        self.logging_signal.clear()


class Worker(QObject):
    """Class that does the serial connection to the instruments
    NOTE: This expects to be run in a separate QThread from the main GUI"""

    # TODO: Add some validation to the incoming parameters, possibly in setters
    # The update interval that readings should be taken at
    interval: float = 50.0  # ms

    csv_file: Optional[TextIO] = None
    csv_writer: Optional[DictWriter] = None

    # Keep track of the addresses of each of the 3 possible devices
    # Ordered dict to ensure that we always read instruments in order when iterating
    instrument_addresses = OrderedDict({1: "", 2: "", 3: ""})

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
                print(f"++addr {gpib_address}")
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

    def run(self):
        """TODO: Description"""

        self.init_connection()

        while True:
            self.logging_signal.wait()

            try:
                self.do_logging()
            except Exception:
                # Ignore it so we try and continue next time
                # TODO: proper error reporting
                traceback.print_exc()
                pass

            time.sleep(float(self.interval) / 1000.0)

    def init_connection(self):
        """Initialize the connection to the Prologix device"""
        # TODO: Set up proper logging!
        with self.lock:
            print("Starting init_connection")
            rm = pyvisa.ResourceManager()

            print(rm.list_resources())
            # TODO: Work out some way to make this dynamic...
            self.connection = rm.open_resource("ASRL/dev/ttyUSB0::INSTR")

    def do_logging(self):
        """Take one set of readings and write them to file"""

        with self.lock:
            print("Starting logging")

            assert self.connection is not None

            results = self.query_instruments()
            print(
                "Writing: ",
                {
                    "timestamp": results[0],
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
                        "timestamp": results[0],
                        "instrument 1": results[1],
                        "instrument 2": results[2],
                        "instrument 3": results[3],
                    }
                )

                self.csv_file.flush()

    def query_instruments(self) -> tuple[str, str, str, str]:
        """Query the instruments and return the timestamp followed by three instrument
        readings."""

        with self.lock:
            measurement_time = str(datetime.now())

            measurements = []
            for i in self.instrument_addresses.values():
                # Instruct prologix to use GPIB address 22
                print(f"Reading {i}")
                if i == "":
                    # No address, add empty entry
                    measurements.append("")
                    continue
                self.connection.write(f"++addr {i}")

                # Clear all memory buffers and disable all triggering
                # self.connection.write("CLEAR")

                val: str = self.connection.query("TRIG SGL")  # Request a single value
                # Value format is e.g. " 9.089320482E+00\r\n"
                val = val.strip(" \r\n")
                measurements.append(val)

            print("returning ", measurement_time, measurements)
            return measurement_time, *measurements
