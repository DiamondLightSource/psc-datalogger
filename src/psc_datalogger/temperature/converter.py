# Handles converting millivolt readings into degrees Celcius for an Analog Devices
# AD8494 Thermocouple Amplifier
"""
The equation governing this is specified as:
V_OUT = (T_MJ * 5 mV/°C) + V_REF
where
- T_MJ is the thermocouple measurement junction temperature.
- V_OUT is the measured output voltage
- V_REF is the reference voltage, which has been configured to 0 on the hardware.
Substituting V_REF=0 and rearranging this equation gives:

T_MJ = V_OUT / 5 mV

i.e. every 5 mV gives 1 degree celcius increase

"""


def volts_to_celcius(volts: str) -> float:
    # Convert to millivolts
    mv = float(volts) * 1000
    temp = mv / 5.0
    # Check the result is at least vaguely sensible
    assert -10.0 <= temp <= 60.0
    return temp
