# type: ignore
import code
import time

import pyvisa

# A test program to set up a connection, via a Prologix controller, to an individual
# GPIB device (specifically an Agilent 3458A Multimeter)


def read_all(instrument):
    while a := instrument.read():
        print(a)

    return


if __name__ == "__main__":
    rm = pyvisa.ResourceManager()

    print(rm.list_resources())

    voltmeter = rm.open_resource("ASRL/dev/ttyUSB0::INSTR")

    # Insruct prologix to use GPIB address 22
    voltmeter.write("++addr 22")
    # Instruct Prologix to enable read-after-write,
    # which allows the controller to write data back to us!
    voltmeter.write("++auto 1")

    time.sleep(1)  # Give Prologix a moment to configure previous commands

    voltmeter.write("PRESET")  # Set a variety of defaults
    voltmeter.write("BEEP 0")  # Disable annoying beeps
    voltmeter.write("CLEAR")  # Clear all memory buffers and disable all triggering
    voltmeter.write("TRIG HOLD")  # Disable triggering

    code.interact(local=locals())

    # Useful commands:
    # val = voltmeter.query("TRIG SGL")
    # read_all(voltmeter)
