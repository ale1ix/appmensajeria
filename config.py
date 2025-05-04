# config.py
import os
basedir = os.path.abspath(os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'tu-clave-secreta-local-y-segura' # Cambia esto
    # Lee DATABASE_URL del entorno, si no existe, usa SQLite local
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024 # Ejemplo 16MB

    # Asegúrate de que no haya nada más fuera de la clase o comentarios aquí abajo
    # a menos que sea otra definición de clase o función válida de Python.