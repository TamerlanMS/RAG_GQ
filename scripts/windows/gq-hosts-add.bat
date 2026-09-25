@echo off
rem ================================================================
rem  GQ Group — открыть консоль по https://bot.gqe-online.kz ВНУТРИ офиса
rem
rem  Внутри офисной сети домен ведёт на внешний адрес роутера, и сайт не
rem  открывается. Этот файл добавляет в hosts строку
rem      192.168.2.158 bot.gqe-online.kz
rem  — и компьютер ходит на сервер напрямую, с настоящим сертификатом (замок).
rem
rem  Запускать двойным щелчком. На ноутбуке, который уносят из офиса,
rem  потом запустить gq-hosts-remove.bat, иначе снаружи сайт не откроется.
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

>>"%HOSTS%" echo.
>>"%HOSTS%" echo %SERVER% %DOMAIN%

ipconfig /flushdns >nul
echo.
echo  Готово. Откройте в браузере: https://%DOMAIN%/console/
echo  (если браузер был открыт — закройте его и откройте снова)
echo.
pause
