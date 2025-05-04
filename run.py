# run.py

# Importar el MÓDULO 'app' y la INSTANCIA 'app' con un alias si quieres
from app import app as flask_app, socketio, db # Renombramos la instancia importada
import app.models

# Usar el alias de la instancia para el decorador
@flask_app.shell_context_processor
def make_shell_context():
    print("Preparando contexto del shell...")
    # ... (resto de la función sin cambios, pero asegúrate de que devuelve 'flask_app' si es necesario)
    context = {'app': flask_app, 'db': db} # Devolver la instancia real
    # ... (añadir modelos al context) ...
    return context

if __name__ == '__main__':
    print("Iniciando servidor de desarrollo con SocketIO (app global)...")
    print(f"Accede en tu navegador a: http://127.0.0.1:5000 o http://localhost:5000")
    # Usar la INSTANCIA importada para correr el servidor
    socketio.run(flask_app, host='0.0.0.0', port=5000, debug=True)