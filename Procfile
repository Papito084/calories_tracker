web: gunicorn --workers 2 --access-logfile - --error-logfile - -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:$PORT
