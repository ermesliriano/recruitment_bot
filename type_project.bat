@echo off
:: Recorre de forma recursiva (/r) buscando archivos .py
for /r %%f in (*.py) do (
    echo.
    echo --- Leyendo: %%f ---
    type "%%f"
    echo.
)
pause