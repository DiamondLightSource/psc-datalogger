import logging
from typing import Callable, Optional, Type

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
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

from psc_datalogger.multimeter import Agilent3458A, Agilent34401A, Multimeter

from . import __version__
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
        self.setWindowTitle(f"PSC Datalogger {__version__}")

        self.connection_manager = ConnectionManager()

        self.create_widgets()

        self.connection_manager.set_status_bar(self.status_bar)
        self.connection_manager.set_nplc_input(self.nplc_input)
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
        interval_input = QLineEdit()
        interval_input.setValidator(QIntValidator())
        interval_input.textEdited.connect(self.connection_manager.set_interval)
        interval_layout.addWidget(interval_input)
        layout.addWidget(interval_frame)

        logfile_widgets = LogFileWidgets(self.connection_manager.set_filepath)
        layout.addWidget(logfile_widgets)

        # Widgets for NPLC
        nplc_frame = QFrame()
        nplc_label = QLabel("NPLC:")
        nplc_layout = QHBoxLayout()
        nplc_frame.setLayout(nplc_layout)
        nplc_layout.addWidget(nplc_label)
        self.nplc_input = QLineEdit()
        self.nplc_input.setText("50")
        self.nplc_input.setValidator(QIntValidator())
        self.nplc_input.textEdited.connect(self.connection_manager.set_nplc)
        nplc_layout.addWidget(self.nplc_input)
        layout.addWidget(nplc_frame)

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
        """Handle when any of the instrument configurations change"""
        for instrument in self.instruments:
            try:
                self.connection_manager.set_instrument(
                    instrument.instrument_number,
                    instrument.isChecked(),
                    instrument.get_address(),
                    instrument.get_temperature_checked(),
                    instrument.get_multimeter(),
                )
            except ValueError:
                # Expected when first activating an instrument; the Address field
                # will be empty
                logging.info(
                    "Exception when initializing instrument "
                    f"{instrument.instrument_number}",
                    exc_info=True,
                )


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
    """Contains widgets to configure a single instrument"""

    def __init__(
        self, instrument_number: int, checked: bool, instrument_changed: Callable
    ) -> None:
        """
        Args:
          instrument_number: The number to use to identify this instance
          checked: True if the widgets should be enabled by default
          instrument_changed: Callback to be called whenever any configuration changes
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
        int_only = QIntValidator()
        int_only.setRange(0, 30)
        self.address_input_box.setValidator(int_only)
        self.address_input_box.editingFinished.connect(instrument_changed)
        self.voltage_radiobutton = QRadioButton("Voltage")
        self.voltage_radiobutton.setChecked(True)
        self.voltage_radiobutton.toggled.connect(instrument_changed)
        self.temperature_radiobutton = QRadioButton("Temperature")
        # Don't need to .connect() the second button as changing the first one
        # triggers a callback that will check both buttons

        grid_layout = QGridLayout(self)

        first_row_layout = QHBoxLayout()

        self.A3458_radiobutton = QRadioButton("3458A")
        self.A3458_radiobutton.setChecked(True)
        self.A3458_radiobutton.toggled.connect(instrument_changed)
        self.A34401_radiobutton = QRadioButton("34401A")

        device_groupbox = QButtonGroup(self)
        device_groupbox.addButton(self.A3458_radiobutton)
        device_groupbox.addButton(self.A34401_radiobutton)

        first_row_layout.addWidget(self.A3458_radiobutton)
        first_row_layout.addWidget(self.A34401_radiobutton)

        grid_layout.addLayout(first_row_layout, 0, 0, Qt.AlignmentFlag.AlignCenter)

        second_row_layout = QHBoxLayout()

        measurement_type_groupbox = QButtonGroup(self)
        measurement_type_groupbox.addButton(self.voltage_radiobutton)
        measurement_type_groupbox.addButton(self.temperature_radiobutton)

        second_row_layout.addWidget(address_label)
        second_row_layout.addWidget(self.address_input_box)
        second_row_layout.addWidget(self.voltage_radiobutton)
        second_row_layout.addWidget(self.temperature_radiobutton)

        grid_layout.addLayout(second_row_layout, 1, 0, Qt.AlignmentFlag.AlignCenter)

        self.setLayout(grid_layout)

    def get_address(self) -> str:
        return self.address_input_box.text()

    def get_temperature_checked(self) -> bool:
        """Returns True if this instrument is configured to read temperature instead of
        voltage"""
        return self.temperature_radiobutton.isChecked()

    def get_multimeter(self) -> Type[Multimeter]:
        return Agilent3458A if self.A3458_radiobutton.isChecked() else Agilent34401A
