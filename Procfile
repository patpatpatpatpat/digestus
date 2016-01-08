web: gunicorn config.wsgi:application
worker: celery worker --app=digestus.taskapp --loglevel=info
