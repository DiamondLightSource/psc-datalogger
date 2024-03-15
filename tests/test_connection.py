import filecmp
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Generator
from unittest.mock import MagicMock, call, patch

import pytest
import pyvisa

# pyright thinks this constant is not exported
from pyvisa.errors import VI_ERROR_TMO  # type: ignore
from pyvisa.resources import RegisterBasedResource, SerialInstrument

from psc_datalogger.connection import (
    ConnectionManager,
    DataWriter,
    InstrumentConfig,
    PrologixNotFoundException,
    Worker,
)


class TestConnectionManager:
    """Testing the ConnectionManager class"""

    @pytest.fixture
    def connmgr(self, qtbot) -> Generator[ConnectionManager, Any, Any]:
        connmgr = ConnectionManager()
        self.mock_status_bar = MagicMock()
        connmgr.set_status_bar(self.mock_status_bar)
        yield connmgr

        if connmgr.thread.isRunning():
            connmgr.thread.quit()
            connmgr._worker._exit()
            time.sleep(0.1)
            qtbot.waitSignal(connmgr.thread.finished)
            assert connmgr.thread.isFinished()

    @patch.object(Worker, "init_connection")
    def test_start(self, mock_init_connection, connmgr: ConnectionManager, qtbot):
        """Test that calling the start() function triggers the thread to begin"""
        connmgr.start()

        qtbot.waitUntil(lambda: connmgr.thread.isRunning())

        # Time for Worker to begin executing its run() method
        time.sleep(0.1)
        mock_init_connection.assert_called_once()

    def test_register_status_bar(
        self,
    ):
        """Test that the ConnectionManager registers the callbacks into the StatusBar
        correctly.

        NOT using connmgr fixture - need to test the behaviour it sets up"""
        mock_status_bar = MagicMock()
        conn_manager = ConnectionManager()
        conn_manager.set_status_bar(mock_status_bar)

        now = datetime.now()
        errmsg = "Test error message"
        # Invoke each of the callbacks
        conn_manager._worker.query_complete.emit(now)
        conn_manager._worker.init_complete.emit()
        conn_manager._worker.error.emit(errmsg)

        # Confirm callbacks triggered
        mock_status_bar.query_complete_callback.assert_called_once_with(now)
        mock_status_bar.init_complete_callback.assert_called_once()
        mock_status_bar.error_callback.assert_called_once_with(errmsg)

    @patch.object(Worker, "validate_parameters")
    def test_start_logging_valid_params(
        self, mock_valid_parameters: MagicMock, connmgr: ConnectionManager
    ):
        """Test that if parameters are valid, the correct actions will occur"""
        mock_valid_parameters.return_value = True

        assert connmgr.start_logging() is True

        assert connmgr.logging_signal.is_set()
        self.mock_status_bar.logging_started.assert_called_once()

    @patch.object(Worker, "validate_parameters")
    def test_start_logging_invalid_params(
        self, mock_valid_parameters: MagicMock, connmgr: ConnectionManager
    ):
        """Test that if parameters are invalid, the correct actions will occur"""
        mock_valid_parameters.return_value = False

        assert connmgr.start_logging() is False

        assert connmgr.logging_signal.is_set() is False
        self.mock_status_bar.logging_started.assert_not_called()

    def test_stop_logging(self, connmgr: ConnectionManager):
        """Test that stop_logging sends the expected signals"""
        connmgr.stop_logging()

        assert connmgr.logging_signal.is_set() is False
        self.mock_status_bar.logging_stopped.assert_called_once()


class TestDataWriter:
    """Testing the DataWriter class"""

    filepath: Path

    @pytest.fixture
    def datawriter(self, tmp_path: Path) -> Generator[DataWriter, Any, Any]:
        self.filepath = tmp_path / "test.csv"
        writer = DataWriter(str(self.filepath))
        yield writer
        writer.close()

    def test_write(self, datawriter: DataWriter):
        """Test that write correctly puts the data into the file"""
        time = datetime(2024, 3, 6, 9, 15, 30)
        datawriter.write(time, "1.23", "4.56", "7.89")

        time = time + timedelta(seconds=30)
        datawriter.write(time, "0.12", "0.34", "0.56")

        expected = Path(__file__).parent / "test_output.csv"
        # Useful debugging code
        # with self.filepath.open("r") as f:
        #     print(f.readlines())
        # with expected.open("r") as f:
        #     print(f.readlines())

        assert filecmp.cmp(self.filepath, expected)


class TestWorker:
    logging_signal: Event

    @pytest.fixture
    def worker(self) -> Generator[Worker, Any, Any]:
        self.logging_signal = Event()
        worker = Worker(self.logging_signal)
        yield worker
        worker._exit()

    def test_set_filepath(self, worker: Worker, tmp_path: Path):
        """Test that setting a filepath creates a writer"""
        file = tmp_path / "something.csv"
        worker.set_filepath(file.as_posix())

        assert worker.writer is not None

    def test_set_filepath_repeatedly(self, worker: Worker, tmp_path: Path):
        """Test that repeatedly setting filepaths creates a new writer each time"""
        file = tmp_path / "something.csv"
        worker.set_filepath(file.as_posix())

        assert worker.writer is not None
        old_writer = worker.writer

        file = tmp_path / "somethingelse.csv"
        worker.set_filepath(file.as_posix())
        assert worker.writer != old_writer

    def test_set_instrument(self, worker: Worker):
        """Test that setting an instrument saves it"""
        # Mock out _init_instrument as it does hardware communication
        mocked_init_instrument = MagicMock()
        worker._init_instrument = mocked_init_instrument

        num = 1
        address = 22
        measure_temp = False
        worker.set_instrument(num, str(address), measure_temp)

        expected_config = InstrumentConfig(address, measure_temp)

        assert worker.instrument_addresses[num] == expected_config
        mocked_init_instrument.assert_called_once_with(expected_config)

    def test_override_instrument(self, worker: Worker):
        """Test that overriding an instrument correctly replaces the config"""
        # Mock out _init_instrument as it does hardware communication
        mocked_init_instrument = MagicMock()
        worker._init_instrument = mocked_init_instrument

        # Initial values
        num = 1
        address = 22
        measure_temp = False
        worker.set_instrument(num, str(address), measure_temp)

        # Override values
        address = 44
        measure_temp = True
        expected_config = InstrumentConfig(address, measure_temp)
        worker.set_instrument(num, str(address), measure_temp)

        assert worker.instrument_addresses[num] == expected_config
        mocked_init_instrument.assert_called_with(expected_config)

    @pytest.mark.parametrize("invalid_value", [-1, 0, 4, 5])
    def test_set_instrument_invalid_values(self, invalid_value: int, worker: Worker):
        """Test that passing invalid values raises expected exception"""
        with pytest.raises(AssertionError):
            worker.set_instrument(invalid_value, "123", False)

    def test_init_instrument(self, worker: Worker):
        """Test that init_instrument sends the expected calls to the hardware"""

        mocked_connection = MagicMock()
        mocked_connection.bytes_in_buffer = 0
        worker.connection = mocked_connection

        address = 22
        worker._init_instrument(InstrumentConfig(address))

        expected_calls = [
            call(f"++addr {address}"),
            call("++auto 1"),
            call("PRESET NORM"),
            call("NPLC 50"),
            call("BEEP 0"),
            call("CLEAR"),
            call("TRIG HOLD"),
        ]

        mocked_connection.write.assert_has_calls(expected_calls, any_order=False)

    @pytest.mark.parametrize("invalid_value", [0, -1])
    def test_init_instrument_invalid_values(self, invalid_value: int, worker: Worker):
        """Check that various invalid parameters raise the expected error"""
        with pytest.raises(ValueError):
            worker._init_instrument(InstrumentConfig(invalid_value))

    def test_validate_parameters(self, worker: Worker):
        """Test that validate_parameters allows through valid parameters"""

        worker.instrument_addresses[1] = InstrumentConfig(23)
        worker.interval = 1
        worker.writer = MagicMock()

        assert worker.validate_parameters()

    @pytest.mark.parametrize(
        "address, interval, writer",
        [
            (0, 1, MagicMock()),
            (22, 0, MagicMock()),
            (22, -1, MagicMock()),
            (22, 1, None),
        ],
    )
    def test_validate_parameters_invalid(
        self, address: int, interval: int, writer: Any, worker: Worker
    ):
        """Test that validate_parameters rejects invalid parameters"""

        worker.instrument_addresses[1] = InstrumentConfig(address)
        worker.interval = interval
        worker.writer = writer

        assert worker.validate_parameters() is False

    @patch("psc_datalogger.connection.pyvisa.ResourceManager")
    def test_init_connection(
        self,
        mock_resource_manager_init: MagicMock,
        worker: Worker,
    ):
        """Test that init_connection can create a valid connection"""

        mock_resource_manager = MagicMock()
        mock_resource_manager.list_resources = MagicMock(
            return_value=(
                "CONN1",
                "CONN2",
            )
        )
        mock_conn = MagicMock(spec=SerialInstrument)
        mock_resource_manager.open_resource = MagicMock(return_value=mock_conn)
        mock_resource_manager_init.return_value = mock_resource_manager

        worker._check_resource_is_prologix = MagicMock(return_value=True)

        worker.init_connection()

        assert worker.connection == mock_conn

    @patch("psc_datalogger.connection.pyvisa.ResourceManager")
    def test_init_connection_no_resources(
        self,
        mock_resource_manager_init: MagicMock,
        worker: Worker,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that init_connection emits expected error when there are no resources"""
        mock_resource_manager = MagicMock()
        mock_resource_manager.list_resources = MagicMock(return_value=())
        mock_resource_manager_init.return_value = mock_resource_manager

        with pytest.raises(PrologixNotFoundException):
            worker.init_connection()

        # Check the right log messages were created
        assert len(caplog.records) == 1
        assert caplog.records[0].message == "No Prologix controller found"

    @patch("psc_datalogger.connection.pyvisa.ResourceManager")
    def test_init_connection_invalid_resource(
        self,
        mock_resource_manager_init: MagicMock,
        worker: Worker,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that init_connection emits expected error when only invalid resources
        exist (i.e. none of them are a Prologix controller)"""

        mock_resource_manager = MagicMock()
        mock_resource_manager.list_resources = MagicMock(return_value=("CONN1",))
        mock_conn = MagicMock(spec=SerialInstrument)
        mock_resource_manager.open_resource = MagicMock(return_value=mock_conn)

        mock_resource_manager_init.return_value = mock_resource_manager

        worker._check_resource_is_prologix = MagicMock(return_value=False)

        with pytest.raises(PrologixNotFoundException):
            worker.init_connection()

        # Check the right log messages were created
        assert len(caplog.records) == 1
        assert caplog.records[0].message == "No Prologix controller found"

    def test_check_resource_is_prologix_with_prologix_resource(
        self,
        worker: Worker,
    ):
        """Test _check_resource_is_prologix returns True for a Prologix resource"""

        resource = MagicMock(spec=SerialInstrument)
        resource.query = MagicMock(return_value="Response to ++help!")

        assert worker._check_resource_is_prologix(resource) is True

    def test_check_resource_is_prologix_not_serial_instrument(
        self,
        worker: Worker,
    ):
        """Test _check_resource_is_prologix returns False if the resource is not a
        SerialInstrument"""

        resource = MagicMock(spec=RegisterBasedResource)

        assert worker._check_resource_is_prologix(resource) is False

    def test_check_resource_is_prologix_no_response(
        self,
        worker: Worker,
    ):
        """Test _check_resource_is_prologix returns False if there is no response to
        the query"""

        resource = MagicMock(spec=SerialInstrument)
        resource.query = MagicMock(return_value="")

        assert worker._check_resource_is_prologix(resource) is False

    def test_check_resource_is_prologix_query_timeout(
        self,
        worker: Worker,
    ):
        """Test _check_resource_is_prologix returns False if there is a timeout on the
        query"""

        resource = MagicMock(spec=SerialInstrument)
        resource.query = MagicMock(side_effect=pyvisa.VisaIOError(VI_ERROR_TMO))

        assert worker._check_resource_is_prologix(resource) is False

    def test_do_logging(self, worker: Worker):
        """Test do_logging sends a query_complete signal and passes data to the
        writer"""

        # Setup all mocks
        worker.connection = True  # type: ignore
        worker.writer = MagicMock()
        worker.query_complete = MagicMock()
        now = datetime.now()
        data = (now, "123", "456", "789")
        worker.query_instruments = MagicMock(return_value=data)

        # Call under test
        worker.do_logging()

        # Checks
        worker.query_complete.emit.assert_called_once_with(now)
        worker.writer.write.assert_called_once_with(
            timestamp=now, ins_1=data[1], ins_2=data[2], ins_3=data[3]
        )

    def test_do_logging_reports_error(self, worker: Worker):
        """Test do_logging sends an error signal with invalid data"""

        # Setup all mocks
        worker.connection = True  # type: ignore
        worker.writer = MagicMock()
        worker.error = MagicMock()
        now = datetime.now()
        data = (now, Worker.ERROR_STRING, "456", "789")
        worker.query_instruments = MagicMock(return_value=data)

        # Call under test
        worker.do_logging()

        # Checks
        worker.error.emit.assert_called_once()  # Don't bother checking string!
        worker.writer.write.assert_called_once_with(
            timestamp=now, ins_1=data[1], ins_2=data[2], ins_3=data[3]
        )

    @patch("psc_datalogger.connection.datetime")
    def test_query_instruments_voltage(
        self, mocked_datetime: MagicMock, worker: Worker
    ):
        """Test querying the (mocked) hardware returns voltage"""
        # Set up mocks
        address = 22
        worker.instrument_addresses[1] = InstrumentConfig(address)
        voltage_str = " 9.089320482E+00\r\n"
        voltage_trimmed = "9.089320482E+00"
        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value=voltage_str)
        worker.connection = MagicMock()
        worker.connection.write = mocked_write
        worker.connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == voltage_trimmed
        assert results[2] == ""
        assert results[3] == ""

        mocked_write.assert_called_once_with(f"++addr {address}")
        mocked_query.assert_called_once_with("TRIG SGL")

    @patch("psc_datalogger.connection.datetime")
    def test_query_instruments_temperature(
        self, mocked_datetime: MagicMock, worker: Worker
    ):
        """Test querying the (mocked) hardware returns the voltage converted to a
        temperature"""
        # Set up mocks
        address = 22
        worker.instrument_addresses[1] = InstrumentConfig(address, convert_to_temp=True)
        voltage_str = "1E-03"
        temperature = "24.993219514361623"  # degrees Celcius, calculated
        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value=voltage_str)
        worker.connection = MagicMock()
        worker.connection.write = mocked_write
        worker.connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == temperature
        assert results[2] == ""
        assert results[3] == ""

        mocked_write.assert_called_once_with(f"++addr {address}")
        mocked_query.assert_called_once_with("TRIG SGL")

    @patch("psc_datalogger.connection.datetime")
    def test_query_instruments_timeout(
        self, mocked_datetime: MagicMock, worker: Worker
    ):
        """Test that a timeout returns an error string"""
        # Set up mocks
        address = 22
        worker.instrument_addresses[1] = InstrumentConfig(address)
        mocked_write = MagicMock()
        mocked_query = MagicMock(side_effect=pyvisa.VisaIOError(VI_ERROR_TMO))
        worker.connection = MagicMock()
        worker.connection.write = mocked_write
        worker.connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == worker.ERROR_STRING
        assert results[2] == ""
        assert results[3] == ""

        mocked_write.assert_called_once_with(f"++addr {address}")
        mocked_query.assert_called_once_with("TRIG SGL")

    @patch("psc_datalogger.connection.datetime")
    def test_query_instruments_invalid_temperature_reading(
        self, mocked_datetime: MagicMock, worker: Worker
    ):
        """Test that an invalid voltage that cannot be converted to a temperature
        returns an error"""
        # Set up mocks
        address = 22
        worker.instrument_addresses[1] = InstrumentConfig(address, convert_to_temp=True)
        voltage_str = "12345"
        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value=voltage_str)
        worker.connection = MagicMock()
        worker.connection.write = mocked_write
        worker.connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == worker.ERROR_STRING
        assert results[2] == ""
        assert results[3] == ""

        mocked_write.assert_called_once_with(f"++addr {address}")
        mocked_query.assert_called_once_with("TRIG SGL")
