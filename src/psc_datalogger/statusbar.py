from datetime import datetime

from PyQt5.QtWidgets import QLabel, QStatusBar


class StatusBar(QStatusBar):
    """The StatusBar for the MainWindow application. Provides feedback to the user on
    the current state of the system"""

    def __init__(self, parent):
        super().__init__(parent)
        self.status_label = QLabel(text="")
        self.addWidget(self.status_label)

    def query_complete_callback(self, timestamp: datetime):
        # Remove microseconds, we don't need to display that much precision
        simple_timestamp = timestamp.isoformat(sep=" ", timespec="seconds")
        self.status_label.setText(
            f"Logging Running. Last data taken: {simple_timestamp}"
        )

    def init_complete_callback(self):
        self.status_label.setText("Serial Connection open")

    def error_callback(self, error: str):
        self.status_label.setText(f"ERROR: {error}")

    def logging_started(self):
        self.status_label.setText("Logging Running. No data collected yet.")

    def logging_stopped(self):
        self.status_label.setText("Logging Stopped.")

    def clear_status(self):
        self.status_label.setText("")
