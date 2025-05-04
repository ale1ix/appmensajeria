# app/__init__.py (Orden Corregido)
import os # Necesario para la condición del scheduler
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_apscheduler import APScheduler
from whitenoise import WhiteNoise

# --- Inicializar Flask ---
print("Iniciando: Creando instancia Flask...")
app = Flask(__name__)
app.config.from_object(Config)
print("Iniciando: Configuración cargada.")

app.wsgi_app = WhiteNoise(app.wsgi_app, root='app/static/', prefix='/static/')
print("Iniciando: Whitenoise configurado.")

# --- Inicializar DB y Login PRIMERO ---
print("Iniciando: Creando instancias DB y LoginManager...")
db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = 'login'
login.login_message = 'Por favor, inicia sesión para acceder a esta página.'
login.login_message_category = 'info'
print("Iniciando: DB y LoginManager configurados.")

# --- Importar modelos AHORA que 'db' y 'login' existen ---
print("Iniciando: Importando modelos...")
from app import models
print("Iniciando: Modelos importados.")

# --- Inicializar otras extensiones ---
print("Iniciando: Creando instancias Migrate, SocketIO, APScheduler...")
migrate = Migrate(app, db)
# !! REVISA cors_allowed_origins para producción más tarde !!
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*") # <<< IMPORTANTE: Necesitarás ajustar cors_allowed_origins
scheduler = APScheduler()
print("Iniciando: Extensiones SocketIO, APScheduler creadas.")

# --- Importar el resto de componentes de la app ---
print("Iniciando: Importando tasks, routes, events...")
from app.tasks import delete_old_messages
from app import routes, events
print("Iniciando: Tasks, routes, events importados.")

# --- Configurar y iniciar Scheduler ---
print("Iniciando: Configurando scheduler...")
# Registrar la tarea ANTES de iniciar el scheduler
# Condición para evitar doble registro en modo debug
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    if not scheduler.get_job('delete_old_messages_job'):
        # Ejecutar cada hora (ajusta 'hours' para probar)
        scheduler.add_job(id='delete_old_messages_job', func=delete_old_messages, trigger='interval', hours=1)
        print("Tarea 'delete_old_messages_job' añadida al scheduler.")
    else:
        print("Tarea 'delete_old_messages_job' ya existe en el scheduler.")

# Inicializar y arrancar el scheduler
scheduler.init_app(app)
scheduler.start()
print("Iniciando: Scheduler iniciado.")

print("Instancia de la aplicación Flask creada y configurada (modo no-factory).")