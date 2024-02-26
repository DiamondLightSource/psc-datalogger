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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .connection import ConnectionManager


def application():
    app = QApplication([])

    window = DataloggerMainWindow()
    window.show()

    app.exec()


class DataloggerMainWindow(QMainWindow):
    """The main window of the Datalogger application"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PSC Datalogger")

        self.connection_manager = ConnectionManager()

        self.create_widgets()

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
            instrument = AgilentWidgets(i + 1, checked, self.handle_address_change)
            self.instruments.append(instrument)
            layout.addWidget(instrument)
            checked = False

        # Widgets for the update interval
        interval_frame = QFrame()
        interval_label = QLabel("Update interval (ms):")
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

    def handle_start_stop(self, checked):
        """Handles starting and stopping logging"""
        print("toggled", checked)

        if checked:
            # Button is pressed, do start actions
            self.start_stop_button.setText(self.stop_text)
            self.connection_manager.start_logging()
        else:
            # Button is unpressed, do stop actions
            self.start_stop_button.setText(self.start_text)
            self.connection_manager.stop_logging()

    def handle_address_change(self):
        """Handle when any of the Agilent GPIB addresses change"""
        for i in self.instruments:
            if i.isChecked():
                address = i.get_address()
            else:
                # Blank the address if the widget is disabled
                address = ""

            self.connection_manager.set_address(i.instrument_number, address)


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
        self, instrument_number: int, checked: bool, address_changed: Callable
    ) -> None:
        super().__init__(f"Instrument {instrument_number}")
        self.instrument_number = instrument_number

        self.setCheckable(True)
        self.setChecked(checked)
        self.toggled.connect(address_changed)

        self.create_widgets(address_changed)

    def create_widgets(self, address_changed: Callable):
        address_label = QLabel("GPIB Address")
        self.address_input_box = QLineEdit()
        self.address_input_box.editingFinished.connect(address_changed)

        layout = QHBoxLayout(self)
        layout.addWidget(address_label)
        layout.addWidget(self.address_input_box)
        self.setLayout(layout)

    def get_address(self):
        return self.address_input_box.text()
