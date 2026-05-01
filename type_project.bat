@echo off
setlocal enabledelayedexpansion

:: Directorio actual
set "target_dir=%~dp0"

echo ====================================================
echo Listando archivos: .py, .env, .txt, .yaml, .sql y Dockerfile
echo Directorio: %target_dir%
echo ====================================================

:: Usamos un formato de cabecera que no use caracteres especiales de redireccion
for /r "%target_dir%" %%f in (*.py .env *.txt *.yaml Dockerfile *.sql) do (
    if exist "%%f" (
        echo.
        echo [ FICHERO: %%f ]
        echo ----------------------------------------------------
        type "%%f"
        echo.
        echo ----------------------------------------------------
    )
)

echo.
echo Proceso finalizado.
pause