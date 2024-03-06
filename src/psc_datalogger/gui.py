import logging
from typing import Callable, Optional

from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .connection import ConnectionManager
from .statusbar import StatusBar


def application():
    app = QApplication([])

    window = DataloggerMainWindow()
    window.show()

    logging.debug("Launching application")
    app.exec()


class DataloggerMainWindow(QMainWindow):
    """The main window of the Datalogger application"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PSC Datalogger")

        self.connection_manager = ConnectionManager()

        self.create_widgets()

        self.connection_manager.set_status_bar(self.status_bar)
        self.connection_manager.start()

    def create_widgets(self) -> None:
        """Create all the widgets for this screen"""

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Widgets for each instrument
        self.instruments: list[AgilentWidgets] = []
        checked = True
        for i in range(3):
            # Use 1-index for GUI labels
            instrument = AgilentWidgets(i + 1, checked, self.handle_instrument_changed)
            self.instruments.append(instrument)
            layout.addWidget(instrument)
            checked = False

        # Widgets for the update interval
        interval_frame = QFrame()
        interval_label = QLabel("Update interval (s):")
        interval_layout = QHBoxLayout()
        interval_frame.setLayout(interval_layout)
        interval_layout.addWidget(interval_label)
        interval_input = QLineEdit()  # TODO: Add numeric-only filters
        interval_input.textEdited.connect(self.connection_manager.set_interval)
        interval_layout.addWidget(interval_input)
        layout.addWidget(interval_frame)

        logfile_widgets = LogFileWidgets(self.connection_manager.set_filepath)
        layout.addWidget(logfile_widgets)

        # Start/Stop logging buttons
        self.start_text = "Start Logging"
        self.stop_text = "Stop Logging"
        self.start_stop_button = QPushButton(self.start_text)
        self.start_stop_button.setCheckable(True)
        self.start_stop_button.toggled.connect(self.handle_start_stop)
        layout.addWidget(self.start_stop_button)

        self.status_bar = StatusBar(self)
        self.setStatusBar(self.status_bar)

    def handle_start_stop(self, checked):
        """Handles starting and stopping logging"""
        logging.debug(f"Start/Stop button is {checked}")
        if checked:
            # Button is pressed, do start actions
            self.start_stop_button.setText(self.stop_text)
            started = self.connection_manager.start_logging()
            if not started:
                error_dialog = QMessageBox(self)
                error_dialog.setIcon(QMessageBox.Icon.Critical)
                error_dialog.setModal(True)
                error_dialog.setWindowTitle("Failed to start logging")
                error_dialog.setText("Unable to start logging data")
                error_dialog.setInformativeText(
                    "Check at least one address, update interval, and logfile is set"
                )
                error_dialog.exec()
                self.start_stop_button.setChecked(False)
        else:
            # Button is unpressed, do stop actions
            self.start_stop_button.setText(self.start_text)
            self.connection_manager.stop_logging()

    def handle_instrument_changed(self):
        """Handle when any of the Agilent GPIB addresses change"""
        for i in self.instruments:
            if i.isChecked():
                address = i.get_address()
                measure_temp = i.get_temperature_checked()
            else:
                # Blank the address if the widget is disabled
                address = ""
                measure_temp = False

            try:
                self.connection_manager.set_instrument(
                    i.instrument_number, address, measure_temp
                )
            except ValueError:
                # We expect ValueError for uninitialized/previously initialized but now
                # disabled instruments
                pass


class LogFileWidgets(QFrame):
    """Contains widgets related to selecting a log file"""

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()

        self.create_widgets()

        self.filename_callback = callback

        self.filename: Optional[str] = None

    def create_widgets(self) -> None:
        file_layout = QHBoxLayout()
        # This is actually a pop-up dialog, not an inline widget
        self.dialog = QFileDialog(None, "Select output logfile")
        self.dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        self.dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        self.dialog.setNameFilter("CSV (*.csv)")
        self.dialog.setDefaultSuffix(".csv")
        self.dialog.fileSelected.connect(self.file_selected)

        file_button = QPushButton("Select Logfile...")
        # Suppress error that `exec` doesn't technically match signature of a PYQT_SLOT
        # - it doesn't affect anything, the return value is discarded
        file_button.clicked.connect(self.dialog.exec)  # type: ignore
        file_layout.addWidget(file_button)

        self.file_readback = QLineEdit()
        self.file_readback.setDisabled(True)
        file_layout.addWidget(self.file_readback)

        self.setLayout(file_layout)

    def file_selected(self, new_path: str) -> None:
        """Handle a new filepath being set"""
        self.filename = new_path
        self.file_readback.setText(new_path)
        self.filename_callback(new_path)


class AgilentWidgets(QGroupBox):
    """Contains widgets describing a single Agilent 3458A instrument"""

    def __init__(
        self, instrument_number: int, checked: bool, instrument_changed: Callable
    ) -> None:
        """
        Args:
          instrument_number: The number to use to identify this instance
          checked: True if the widgets should be enabled by default
          instrument_changed: Callback to be called whenever an address changes
        """
        super().__init__(f"Instrument {instrument_number}")
        self.instrument_number = instrument_number

        self.setCheckable(True)
        self.setChecked(checked)
        self.toggled.connect(instrument_changed)

        self.create_widgets(instrument_changed)

    def create_widgets(self, instrument_changed: Callable) -> None:
        address_label = QLabel("GPIB Address")
        self.address_input_box = QLineEdit()
        self.address_input_box.editingFinished.connect(instrument_changed)
        self.voltage_radiobutton = QRadioButton("Voltage")
        self.voltage_radiobutton.setChecked(True)
        self.voltage_radiobutton.toggled.connect(instrument_changed)
        self.temperature_radiobutton = QRadioButton("Temperature")
        # Don't need to .connect() the second button as changing the first one
        # triggers a callback that will check both buttons

        layout = QHBoxLayout(self)
        layout.addWidget(address_label)
        layout.addWidget(self.address_input_box)
        layout.addWidget(self.voltage_radiobutton)
        layout.addWidget(self.temperature_radiobutton)
        self.setLayout(layout)

    def get_address(self) -> str:
        return self.address_input_box.text()

    def get_temperature_checked(self) -> bool:
        """Returns True if this instrument is configured to read temperature instead of
        voltage"""
        return self.temperature_radiobutton.isChecked()
