import filecmp
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Generator, List, Type
from unittest.mock import MagicMock, _Call, call, patch

import pytest
import pyvisa
from pytest import LogCaptureFixture

# pyright thinks this constant is not exported
from pyvisa.errors import VI_ERROR_TMO  # type: ignore
from pyvisa.resources import RegisterBasedResource, SerialInstrument

from psc_datalogger.connection import (
    ConnectionManager,
    ConnectionNotInitialized,
    DataWriter,
    InstrumentConfig,
    PrologixNotFoundException,
    Worker,
)
from psc_datalogger.multimeter import Agilent3458A, Agilent34401A, Multimeter


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

    def test_set_instrument_handles_expected_exception(
        self, connmgr: ConnectionManager, caplog: pytest.LogCaptureFixture
    ):
        """Test that set_instrument handles the ConnectionNotInitialized exception"""

        mocked_worker = MagicMock()
        mock_set_instrument = MagicMock(side_effect=ConnectionNotInitialized)
        mocked_worker.set_instrument = mock_set_instrument
        connmgr._worker = mocked_worker

        with caplog.at_level(logging.ERROR):
            connmgr.set_instrument(
                0, False, "10", False, Agilent3458A
            )  # parameters don't matter

        # Check that the expected message appears
        assert "Could not set instrument" in caplog.text

    def test_set_nplc_handles_expected_exception(
        self, connmgr: ConnectionManager, caplog: pytest.LogCaptureFixture
    ):
        """Test that set_nplc handles the ConnectionNotInitialized exception"""

        mocked_worker = MagicMock()
        mock_set_nplc = MagicMock(side_effect=ConnectionNotInitialized)
        mocked_worker.set_nplc = mock_set_nplc
        connmgr._worker = mocked_worker

        with caplog.at_level(logging.ERROR):
            connmgr.set_nplc("123")  # parameters don't matter

        # Check that the expected message appears
        assert "Could not set NPLC" in caplog.text


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


def multimeter_naming(val):
    """Function to provide readable names for Pytest parameterized tests"""
    if isinstance(val, Multimeter):
        return val.__class__
    return ""


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
        enabled = True
        address = 22
        measure_temp = False
        multimeter = MagicMock()
        multimeter_returner = MagicMock(return_value=multimeter, spec=Agilent3458A)
        worker.set_instrument(
            num,
            enabled,
            str(address),
            measure_temp,
            multimeter_returner,  # type: ignore
        )

        expected_config = InstrumentConfig(enabled, address, measure_temp, multimeter)

        multimeter_returner.assert_called_once_with()
        assert worker.instrument_configs[num] == expected_config
        mocked_init_instrument.assert_called_once_with(expected_config)

    def test_override_instrument(self, worker: Worker):
        """Test that overriding an instrument correctly replaces the config"""
        # Mock out _init_instrument as it does hardware communication
        mocked_init_instrument = MagicMock()
        worker._init_instrument = mocked_init_instrument

        # Initial values
        num = 1
        enabled = True
        address = 22
        measure_temp = False
        worker.set_instrument(num, enabled, str(address), measure_temp, Agilent3458A)

        # Override values
        enabled = False
        address = 44
        measure_temp = True
        multimeter = MagicMock()
        multimeter_returner = MagicMock(return_value=multimeter, spec=Agilent3458A)
        expected_config = InstrumentConfig(enabled, address, measure_temp, multimeter)
        worker.set_instrument(
            num,
            enabled,
            str(address),
            measure_temp,
            multimeter_returner,  # type: ignore
        )

        multimeter_returner.assert_called_once_with()
        assert worker.instrument_configs[num] == expected_config
        mocked_init_instrument.assert_called_with(expected_config)

    @pytest.mark.parametrize("invalid_value", [-1, 0, 4, 5])
    def test_set_instrument_invalid_values(self, invalid_value: int, worker: Worker):
        """Test that passing invalid values raises expected exception"""
        with pytest.raises(AssertionError):
            worker.set_instrument(invalid_value, True, "123", False, Agilent3458A)

    @pytest.mark.parametrize(
        "multimeter, expected_calls",
        [
            (
                Agilent3458A(),
                [
                    call("++addr 22"),
                    call("++auto 1"),
                    call("PRESET NORM"),
                    call("BEEP 0"),
                    call("TRIG HOLD"),
                    call("++addr 22"),
                    call("++auto 1"),
                    call("NPLC 50"),
                ],
            ),
            (
                Agilent34401A(),
                [
                    call("++addr 22"),
                    call("++auto 0"),
                    call("*RST"),
                    call("CONFigure:VOLTage:DC 10, 0.003"),
                    call("SYSTEM:BEEPER:STATE OFF"),
                    call("++addr 22"),
                    call("++auto 0"),
                    call("VOLT:DC:NPLCYCLES 50"),
                ],
            ),
        ],
        ids=multimeter_naming,
    )
    def test_init_instrument(
        self, worker: Worker, multimeter: Multimeter, expected_calls: List[_Call]
    ):
        """Test that init_instrument sends the expected calls to the hardware"""

        mocked_connection = MagicMock(spec=SerialInstrument)
        mocked_connection.bytes_in_buffer = 0
        worker._connection = mocked_connection
        worker.nplc_input = MagicMock()
        worker.nplc_input.text = MagicMock(return_value=50)

        enabled = True
        address = 22  # Note: Duplicated in the parameterized calls
        worker._init_instrument(
            InstrumentConfig(enabled, address, multimeter=multimeter)
        )

        mocked_connection.write.assert_has_calls(expected_calls, any_order=False)

    def test_init_instrument_empties_read_buffer(self, worker: Worker):
        """Test that _init_instrument reads all of the bytes out of the connection
        before returning"""
        mocked_connection_bytes_in_buffer = MagicMock(side_effect=[100, 50, 25, 0])
        worker._connection_bytes_in_buffer = mocked_connection_bytes_in_buffer

        mocked_connection = MagicMock()
        mocked_connection.read = MagicMock(side_effect=["some", "random", "data"])
        worker._connection = mocked_connection
        worker.nplc_input = MagicMock()

        enabled = True
        address = 22
        worker._init_instrument(InstrumentConfig(enabled, address))

        assert mocked_connection.read.call_count == 3

    def test_init_instrument_disabled_instrument(
        self,
        worker: Worker,
        caplog: pytest.LogCaptureFixture,
    ):
        """Check that passing a disabled instrument causes nothing to happen"""

        instrument = InstrumentConfig(False)

        with caplog.at_level(logging.DEBUG):
            worker._init_instrument(instrument)

        # Check the right log messages were created
        assert len(caplog.records) == 2
        assert (
            caplog.records[1].message
            == f"Skipping _init_instrument for instrument {instrument.address}"
        )

    @pytest.mark.parametrize("invalid_value", [0, -1])
    def test_init_instrument_invalid_values(self, invalid_value: int, worker: Worker):
        """Check that various invalid parameters raise the expected error"""
        with pytest.raises(ValueError):
            worker._init_instrument(InstrumentConfig(True, invalid_value))

    def test_set_nplc(self, worker: Worker):
        """Test that set_nplc works as expected for good values"""

        # Setup
        worker.instrument_configs[1] = InstrumentConfig(True, 5)
        worker._connection = MagicMock()

        nplc = "100"

        # Run test function
        worker.set_nplc(nplc)

        # Check the set NPLC command was set and the timeout was increased
        worker._connection.write.assert_any_call(f"NPLC {nplc}")
        assert worker._connection.timeout == 10000

    @pytest.mark.parametrize(
        "multimeter, invalid_value",
        [
            (Agilent3458A, "-1"),
            (Agilent3458A, "0"),
            (Agilent3458A, "2001"),
            (Agilent3458A, "999999"),
            (Agilent34401A, "-1"),
            (Agilent34401A, "0"),
            (Agilent34401A, "101"),
        ],
    )
    def test_set_nplc_invalid_value(
        self, multimeter: Type[Multimeter], invalid_value: str, worker: Worker
    ):
        """Test that set_nplc rejects invalid values"""

        worker.instrument_configs[1] = InstrumentConfig(
            True, 5, multimeter=multimeter()
        )
        worker._connection = MagicMock()
        worker.error = MagicMock()

        worker.set_nplc(invalid_value)

        worker.error.emit.assert_called_once_with(
            f"NPLC value {invalid_value} outside allowed range "
            f"{multimeter.nplc_min} - {multimeter.nplc_max}"
        )

    def test_validate_parameters(self, worker: Worker):
        """Test that validate_parameters allows through valid parameters"""

        worker.instrument_configs[1] = InstrumentConfig(True, 23)
        worker.interval = 1
        worker.writer = MagicMock()
        worker.nplc_input = MagicMock()

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

        worker.instrument_configs[1] = InstrumentConfig(True, address)
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

        assert worker._connection == mock_conn

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
        worker._connection = True  # type: ignore
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
        worker._connection = True  # type: ignore
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

    @patch("psc_datalogger.multimeter.time")
    @pytest.mark.parametrize(
        "multimeter, expected_writes, expected_queries",
        [
            (
                Agilent34401A(),
                [
                    call("++addr 22"),
                    call("++auto 0"),
                    call("VOLT:DC:NPLCYCLES?"),
                    call("INIT"),
                    call("FETCH?"),
                ],
                [
                    call("++read eoi"),
                    call("++read eoi"),
                ],
            ),
            (
                Agilent3458A(),
                [call("++addr 22")],
                [
                    call("TRIG SGL"),
                ],
            ),
        ],
        ids=multimeter_naming,
    )
    def test_query_instrument_sends_expected_commands(
        self,
        mocked_time: MagicMock,
        worker: Worker,
        multimeter: Multimeter,
        expected_writes: List[_Call],
        expected_queries: List[_Call],
    ):
        """Test that the query_instrument function sends the right commands to the
        multimeter"""
        address = 22  # NOTE: Also in parameters
        worker.instrument_configs[1] = InstrumentConfig(
            True, address, multimeter=multimeter
        )

        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value="1")
        worker._connection = MagicMock()
        worker._connection.write = mocked_write
        worker._connection.query = mocked_query

        # Call under test
        worker.query_instruments()

        # mocked_write.assert_called_once_with(f"++addr {address}")
        mocked_write.assert_has_calls(expected_writes, any_order=False)
        mocked_query.assert_has_calls(expected_queries, any_order=False)

    @patch("psc_datalogger.connection.datetime")
    @pytest.mark.parametrize(
        "multimeter, voltage_reading",
        [
            (Agilent34401A(), "\x009.089320482E+00"),
            (Agilent3458A(), "\x00 9.089320482E+00"),
        ],
        ids=multimeter_naming,
    )
    def test_query_instruments_voltage(
        self,
        mocked_datetime: MagicMock,
        worker: Worker,
        multimeter: Multimeter,
        voltage_reading: str,
    ):
        """Test querying the (mocked) hardware returns voltage"""
        # Set up mocks
        address = 22
        worker.instrument_configs[1] = InstrumentConfig(
            True, address, multimeter=multimeter
        )

        voltage_trimmed = "9.089320482E+00"  # The cleaned up string we expect
        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value=voltage_reading)
        worker._connection = MagicMock()
        worker._connection.write = mocked_write
        worker._connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == voltage_trimmed
        assert results[2] == ""
        assert results[3] == ""

    @patch("psc_datalogger.connection.datetime")
    @pytest.mark.parametrize(
        "multimeter, query_returns",
        [
            # First "10" is for the NPLC query
            (Agilent34401A(), ["10", "\x001E-03"]),
            (Agilent3458A(), ["\x00 1E-03"]),
        ],
        ids=multimeter_naming,
    )
    def test_query_instruments_temperature(
        self,
        mocked_datetime: MagicMock,
        worker: Worker,
        multimeter: Multimeter,
        query_returns: str,
    ):
        """Test querying the (mocked) hardware returns the voltage converted to a
        temperature"""
        # Set up mocks
        address = 22
        worker.instrument_configs[1] = InstrumentConfig(
            True, address, multimeter=multimeter, convert_to_temp=True
        )
        temperature = "0.2"  # degrees Celcius, calculated from voltage_str
        mocked_write = MagicMock()
        mocked_query = MagicMock(side_effect=query_returns)
        worker._connection = MagicMock()
        worker._connection.write = mocked_write
        worker._connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == temperature
        assert results[2] == ""
        assert results[3] == ""

    @patch("psc_datalogger.connection.datetime")
    @pytest.mark.parametrize(
        "multimeter",
        [
            Agilent34401A(),
            Agilent3458A(),
        ],
        ids=multimeter_naming,
    )
    def test_query_instruments_timeout(
        self,
        mocked_datetime: MagicMock,
        worker: Worker,
        multimeter: Multimeter,
        caplog: LogCaptureFixture,
    ):
        """Test that a timeout returns an error string"""
        # Set up mocks
        address = 22
        worker.instrument_configs[1] = InstrumentConfig(
            True, address, multimeter=multimeter
        )
        mocked_write = MagicMock()
        mocked_query = MagicMock(side_effect=pyvisa.VisaIOError(VI_ERROR_TMO))
        worker._connection = MagicMock()
        worker._connection.write = mocked_write
        worker._connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == worker.ERROR_STRING
        assert results[2] == ""
        assert results[3] == ""

        assert "Exception reading from address " in caplog.text

    @patch("psc_datalogger.connection.datetime")
    @pytest.mark.parametrize(
        "multimeter",
        [
            Agilent34401A(),
            Agilent3458A(),
        ],
        ids=multimeter_naming,
    )
    def test_query_instruments_invalid_temperature_reading(
        self,
        mocked_datetime: MagicMock,
        worker: Worker,
        multimeter: Multimeter,
        caplog: LogCaptureFixture,
    ):
        """Test that an invalid voltage that cannot be converted to a temperature
        returns an error"""
        # Set up mocks
        address = 22
        worker.instrument_configs[1] = InstrumentConfig(
            True, address, multimeter=multimeter, convert_to_temp=True
        )
        voltage_str = "0.5"  # Value is too large to convert to temp
        mocked_write = MagicMock()
        mocked_query = MagicMock(return_value=voltage_str)
        worker._connection = MagicMock()
        worker._connection.write = mocked_write
        worker._connection.query = mocked_query

        now = datetime.now()
        mocked_datetime.now.return_value = now

        # Call under test
        results = worker.query_instruments()

        # Assert results
        assert results[0] == now
        assert results[1] == worker.ERROR_STRING
        assert results[2] == ""
        assert results[3] == ""

        assert f"Exception converting value {voltage_str} to temperature" in caplog.text

    def test_connection_check_no_connection(self, worker: Worker):
        """Test that when there is no connection the expected exception is raised"""
        with pytest.raises(ConnectionNotInitialized):
            worker._connection_check()
