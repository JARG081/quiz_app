#!/bin/sh
set -e

python - <<'PY'
import os
import sys
import time

import psycopg2

host = os.getenv('DB_HOST', 'db')
port = os.getenv('DB_PORT', '5432')
name = os.getenv('DB_NAME', 'quiz_platform')
user = os.getenv('DB_USER', 'quiz_platform')
password = os.getenv('DB_PASSWORD', 'quiz_platform')

for _ in range(30):
	try:
		conn = psycopg2.connect(
			host=host,
			port=port,
			dbname=name,
			user=user,
			password=password,
		)
		conn.close()
		sys.exit(0)
	except Exception:
		time.sleep(2)

sys.exit(1)
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn quiz_platform.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
