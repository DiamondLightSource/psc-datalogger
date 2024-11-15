[![CI](https://github.com/DiamondLightSource/psc-datalogger/actions/workflows/ci.yml/badge.svg)](https://github.com/DiamondLightSource/psc-datalogger/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/DiamondLightSource/psc-datalogger/branch/main/graph/badge.svg)](https://codecov.io/gh/DiamondLightSource/psc-datalogger)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

# psc_datalogger

Provide a GUI interface to allow logging measurements from one to three Multimeters. Supported multimeters are the
Agilent 3458A and 34401A devices.
Logging is done at a configurable interval. It can be also be configured to convert voltage readings into
a temperature, if a Analog Devices AD8494 Thermocouple Amplifier is connected to the multimeter.
The data is output in a CSV format.

![GUI](images/gui.png)

# Installation

The simplest way to install this program is to use `pip` to install it directly from this repository:

```
python -m venv venv
source venv/bin/activate
pip install git+https://github.com/DiamondLightSource/psc-datalogger.git
```

Then the application can be started:

```
psc-datalogger
```

# Building Windows Executable

This project can be built and distriubted as a Windows `.exe` file. The tool used, `pyinstaller`, is included in the Dev dependencies.

To create the application follow these instructions:

```
git clone https://github.com/DiamondLightSource/psc-datalogger.git
cd psc-datalogger
python -m venv venv
venv\Scripts\activate
pip install .[dev]
pyinstaller --hidden-import pyvisa_py --noconfirm --log-level=WARN --onefile --name psc_datalogger src\psc_datalogger\__main__.py
```

The application will appear in the `dist` folder. Each parameter of the `pyinstaller` command line is:

- `--hidden-import pyvisa_py` - The `PyVISA-py` module is actually stored on disk as `pyvisa_py`, so tell the installer to include it explicitly
- `--noconfirm` - Don't warn when about to delete a previous build
- `--log-level=WARN` - Only print warning (or higher) log messages when building. Note a successful build does emit a warning about "sip" module not being found, and another saying "only basenames are supported with ctypes imports". These appear to be harmless.
- `--onefile` - Package the build into a single `.exe` file (as opposed to a single directory)
- `--name psc_datalogger` - Give a name to the build application (otherwise it copies the name of the start script)
- `src\psc_datalogger\__main__.py` - Specify the main entry point of the application

Lastly, move the built application to a known distribution location under "S:\Technical\Power_Supplies\Software\Python_datalogger"
