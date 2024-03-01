from collections import namedtuple

# Handles converting millivolt readings into degrees Celcius for a Type K Thermocouple
# Valid for -10 -> 59 degrees Celcius.

"""
The conversion is done by using the calculated coefficients of a cubic equation that
models the data found here:
https://es.omega.com/temperature/pdf/Type_K_Thermocouple_Reference_Table.pdf
(Relevant range copied into data.csv )

To recreate the polynomial follow these steps:
- Format the data.csv file:
    - Remove comments
    - Delete first column (the degrees celcius)
    - Delete the penultimate column (These values are repeated as the first element
      of the next row)
    - Delete the final column (another degrees celcius reading)
    - Save as "formatted_data.txt"
- Read it into matlab (and transpose):
    - v = load("formatted_data.txt")';
- Create time series:
    - t = (-10:59)';
- Set long format:
    - format long
- Fit the polynomial:
    - f3 = polyfit(v, t, 3)

The final line should print out the polynomials:
f3 =
   0.039232630522331  -0.391455002477827  25.346167279763222  -0.000725393446104
"""

# The coefficients of the equation y = a + bx + cx^2 + dx^3
Coeffs = namedtuple("Coeffs", ["a", "b", "c", "d"])
coefficients = Coeffs(
    -0.000725393446104,
    25.346167279763222,
    -0.391455002477827,
    0.039232630522331,
)


def volts_to_celcius(millivolts):
    assert (
        -0.778 < millivolts < 2.436
    ), f"millivolt reading {millivolts} outside of modelled range"

    return (
        coefficients.a
        + coefficients.b * millivolts
        + coefficients.c * millivolts**2
        + coefficients.d * millivolts**3
    )
