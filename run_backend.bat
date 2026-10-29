@echo off
set USE_MYSQL=true
set MYSQL_USER=root
set MYSQL_PASSWORD=root
set MYSQL_DATABASE=laptop_mon
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306
echo ========================================================
echo Starting Laptop Monitoring Backend (MySQL 8.0)
echo Host: http://127.0.0.1:8000/
echo ========================================================
python backend/manage.py runserver 8000 --settings=config.settings.development
pause
