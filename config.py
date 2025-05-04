import os
basedir = os.path.abspath(os.path.dirname(__file__))
# Importamos la función para cargar variables de entorno desde .env
from dotenv import load_dotenv

# Obtenemos la ruta absoluta del directorio donde se encuentra este archivo (config.py)
basedir = os.path.abspath(os.path.dirname(__file__))

# Cargamos las variables definidas en el archivo .env (si existe)
# Esto permite tener secretos fuera del código fuente
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    """Clase base de configuración."""

    # --- Clave Secreta ---
    # Esencial para la seguridad de sesiones, formularios CSRF, etc.
    # Intenta obtenerla de una variable de entorno llamada SECRET_KEY.
    # Si no existe, usa una clave por defecto (¡SOLO PARA DESARROLLO! Cámbiala por una segura en .env o en PythonAnywhere).
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'cambiame-por-una-clave-super-secreta-y-aleatoria'

    # --- Base de Datos ---
    # Configuración para SQLAlchemy.
    # Intenta obtener la URL de conexión de la variable de entorno DATABASE_URL.
    # Si no existe, configura SQLite por defecto en un archivo llamado 'app.db'
    # dentro del directorio 'basedir' (la raíz del proyecto).
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')

    # Desactiva el sistema de eventos de SQLAlchemy, que no usaremos y consume memoria.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- NUEVA CONFIGURACIÓN ---
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    # Extensiones permitidas (importante por seguridad)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    # Tamaño máximo (opcional, ej: 16MB)
    MAX_CONTENT_LENGTH = 16 * 2000 * 2000

    # Configuración específica para el modo Mantenimiento (ejemplo)
    # SITE_CLOSED = os.environ.get('SITE_CLOSED', 'False').lower() in ['true', '1', 't']