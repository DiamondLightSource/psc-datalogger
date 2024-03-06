import math

import pytest

from psc_datalogger.thermocouple.thermocouple import volts_to_celcius

# Tests for the thermocouple voltage -> degrees Celcius conversion.

# This is how close the calculated temperature must be to the real temperature
TOLERANCE = 0.01  # degC


@pytest.mark.parametrize(
    "input_millivolts, expected_temp",
    [
        (-0.392 * 10**-3, -10),
        (0.0 * 10**-3, 0.0),
        (1.203 * 10**-3, 30),
        (2.395 * 10**-3, 59),
    ],
)
def test_volts_to_celcius_valid(input_millivolts, expected_temp):
    """Test that a handful of millivolt readings produce the correct output temperature
    to within TOLERANCE."""
    calculated_temp = volts_to_celcius(input_millivolts)
    assert math.isclose(expected_temp, calculated_temp, abs_tol=TOLERANCE)


@pytest.mark.parametrize(
    "invalid_value",
    [-1 * 10**-3, -0.393 * 10**-3, 2.396 * 10**-3, 3 * 10**-3, 10 * 10**-3],
)
def test_volts_to_celcius_invalid_values(invalid_value):
    """Test that various values are all invalid i.e. outside modelled range"""
    with pytest.raises(AssertionError):
        volts_to_celcius(invalid_value)
