@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "requirements.txt" goto missing_requirements
if exist "%VENV_PYTHON%" goto validate_environment
goto prepare_environment

:validate_environment
"%VENV_PYTHON%" --version >nul 2>&1
if not errorlevel 1 goto check_dependencies
echo The existing .venv belongs to another Python installation and will be rebuilt.

:prepare_environment
echo Preparing the local Python environment. This is only required once.
py -3 --version >nul 2>&1
if not errorlevel 1 goto create_with_py
python --version >nul 2>&1
if not errorlevel 1 goto create_with_python
goto missing_python

:create_with_py
py -3 -m venv --clear --system-site-packages ".venv"
if errorlevel 1 goto environment_failed
goto check_dependencies

:create_with_python
python -m venv --clear --system-site-packages ".venv"
if errorlevel 1 goto environment_failed

:check_dependencies
"%VENV_PYTHON%" -c "import jinja2, netmiko" >nul 2>&1
if not errorlevel 1 goto check_gui

echo Installing required Python packages into .venv...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 goto install_failed

:check_gui
"%VENV_PYTHON%" -c "import tkinter, jinja2, netmiko" >nul 2>&1
if errorlevel 1 goto gui_requirements_failed
if /i "%~1"=="--setup-only" goto setup_complete

echo Opening Network Precheck / Postcheck...
"%VENV_PYTHON%" -m network_prepost_check.gui
if errorlevel 1 goto launch_failed
goto finished

:missing_requirements
echo ERROR: requirements.txt was not found beside Launch_GUI.bat.
goto failed

:missing_python
echo ERROR: Python 3 was not found. Install Python 3 with Tcl/Tk support, then run this file again.
goto failed

:environment_failed
echo ERROR: The local .venv environment could not be created.
goto failed

:install_failed
echo ERROR: Required packages could not be installed.
echo Check the network or proxy settings, then run this file again.
goto failed

:gui_requirements_failed
echo ERROR: Python is missing Tcl/Tk GUI support or a required package is unavailable.
echo Install a standard Python distribution with Tcl/Tk support, then run this file again.
goto failed

:launch_failed
echo ERROR: The GUI closed because of an error. Review the message above.

:failed
pause
exit /b 1

:setup_complete
echo The local Python environment is ready.

:finished
endlocal
exit /b 0
