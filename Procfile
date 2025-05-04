web: gunicorn --worker-class eventlet -w 1 app:socketio
worker: python -c 'from app import app; from app.tasks import delete_old_messages; with app.app_context(): delete_old_messages()'