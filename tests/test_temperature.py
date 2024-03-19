import math

import pytest

from psc_datalogger.temperature.converter import volts_to_celcius

# Tests for the thermocouple voltage -> degrees Celcius conversion.

# This is how close the calculated temperature must be to the real temperature
TOLERANCE = 0.01  # degC


@pytest.mark.parametrize(
    "input_volts, expected_temp",
    [
        (0.2, 40.0),
        (-0.01, -2.0),
        (0.0, 0.0),
        (0.11, 22.0),
    ],
)
def test_volts_to_celcius_valid(input_volts, expected_temp):
    """Test that a handful of millivolt readings produce the correct output temperature
    to within TOLERANCE."""
    calculated_temp = volts_to_celcius(input_volts)
    assert math.isclose(expected_temp, calculated_temp, abs_tol=TOLERANCE)


@pytest.mark.parametrize(
    "invalid_value",
    [-5.1 * 10**-2, 3.1 * 10**-1],
)
def test_volts_to_celcius_invalid_values(invalid_value):
    """Test that various values are all invalid i.e. outside modelled range"""
    with pytest.raises(AssertionError):
        volts_to_celcius(invalid_value)
