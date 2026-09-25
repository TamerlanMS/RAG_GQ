@echo off
rem ================================================================
rem  GQ Group — отменить gq-hosts-add.bat
rem
rem  Убирает из hosts строку для bot.gqe-online.kz. Нужно на ноутбуке,
rem  который работает вне офиса: там домен должен идти через интернет.
rem ================================================================
chcp 65001 >nul
setlocal

rem Нужны права администратора: файл hosts системный.
rem Если их нет — перезапускаем этот же файл с запросом прав (окно UAC).
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
set "DOMAIN=bot.gqe-online.kz"
set "SERVER=192.168.2.158"
set "TMPFILE=%TEMP%\hosts.gq.tmp"

rem Копия исходного hosts — один раз, при первом запуске.
if not exist "%HOSTS%.gq-backup" copy /Y "%HOSTS%" "%HOSTS%.gq-backup" >nul

rem Убираем прежние строки с этим доменом, чтобы не было дублей.
findstr /V /I /C:"%DOMAIN%" "%HOSTS%" > "%TMPFILE%"
copy /Y "%TMPFILE%" "%HOSTS%" >nul
del "%TMPFILE%" >nul 2>&1

ipconfig /flushdns >nul
echo.
echo  Готово. Строка для %DOMAIN% удалена из hosts.
echo.
pause
