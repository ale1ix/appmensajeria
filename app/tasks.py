# app/tasks.py
from datetime import datetime, timedelta, timezone
# QUITAR la importación de app y db de aquí
from app.models import Message # Mantener esta
from urllib.parse import urlparse, unquote
import os


def delete_old_messages():
    """
    Tarea para eliminar mensajes con más de 3 horas de antigüedad
    y los archivos de IMAGEN asociados (no stickers).
    """
    # Importar 'app' y 'db' AQUÍ DENTRO, cuando la función se ejecute
    from app import db, app

    # Necesitamos un contexto de aplicación para acceder a db y app.static_folder
    with app.app_context():
        try:
            three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=3)
            print(f"[{datetime.now(timezone.utc).isoformat()}] Ejecutando tarea: Eliminando mensajes y archivos de imagen anteriores a {three_hours_ago.isoformat()}...")

            messages_to_delete = Message.query.filter(Message.timestamp < three_hours_ago).all()
            count = len(messages_to_delete)
            deleted_files_count = 0
            failed_deletions = []

            if count > 0:
                print(f"Encontrados {count} mensajes para eliminar.")
                # --- Bucle para intentar borrar archivos ANTES de borrar de la DB ---
                for msg in messages_to_delete:
                    # Solo intentar borrar si es un mensaje de tipo 'image'
                    if msg.message_type == 'image':
                        try:
                            # msg.body contiene la URL relativa, ej: /static/uploads/images/uuid.jpg
                            url_path = urlparse(msg.body).path # Extrae la parte de la ruta

                            # Quitar el prefijo '/static/' para obtener la ruta relativa al static folder
                            # Usar unquote para manejar posibles caracteres especiales en nombres de archivo
                            relative_path = unquote(url_path.removeprefix('/static/'))

                            # Asegurarse que la ruta sea segura y esté dentro de la carpeta esperada
                            # (Evitar ataques tipo Path Traversal)
                            image_upload_folder = os.path.join('uploads', 'images') # Carpeta relativa esperada
                            if relative_path.startswith(image_upload_folder):
                                # Construir ruta absoluta del sistema de archivos
                                fs_path = os.path.join(app.static_folder, relative_path)
                                # Normalizar ruta por seguridad
                                fs_path = os.path.normpath(fs_path)

                                # Doble check para asegurar que estamos dentro de static_folder
                                if fs_path.startswith(os.path.normpath(app.static_folder)) and os.path.exists(fs_path):
                                    print(f"Intentando eliminar archivo de imagen: {fs_path}")
                                    os.remove(fs_path)
                                    deleted_files_count += 1
                                    print(f"Archivo eliminado: {fs_path}")
                                elif not os.path.exists(fs_path):
                                     print(f"Archivo no encontrado (ya borrado?): {fs_path}")
                                else:
                                     print(f"WARN: Ruta calculada {fs_path} parece insegura o fuera de {app.static_folder}. No se elimina.")
                                     failed_deletions.append(fs_path)

                            else:
                                 print(f"WARN: La ruta en msg {msg.id} ('{relative_path}') no empieza con '{image_upload_folder}'. No se elimina.")
                                 # Podría ser una URL externa o un sticker guardado incorrectamente como imagen?

                        except OSError as e:
                             # Error al borrar archivo (permisos, etc.)
                            print(f"Error al eliminar archivo {fs_path if 'fs_path' in locals() else msg.body}: {e}")
                            failed_deletions.append(fs_path if 'fs_path' in locals() else msg.body)
                        except Exception as e:
                             # Otro error inesperado procesando el mensaje/ruta
                            print(f"Error procesando archivo para msg {msg.id} ({msg.body}): {e}")
                            failed_deletions.append(msg.body)

                # --- Borrar TODOS los mensajes encontrados de la DB ---
                # Se hace después de intentar borrar los archivos asociados
                for msg in messages_to_delete:
                    db.session.delete(msg)

                db.session.commit()
                print(f"Tarea completada: {count} mensajes antiguos eliminados de la DB.")
                if deleted_files_count > 0:
                     print(f"Se eliminaron {deleted_files_count} archivos de imagen asociados.")
                if failed_deletions:
                     print(f"ATENCIÓN: No se pudieron eliminar {len(failed_deletions)} archivos:")
                     for failed_path in failed_deletions:
                         print(f"  - {failed_path}")
            else:
                print("Tarea completada: No se encontraron mensajes antiguos para eliminar.")

        except Exception as e:
            db.session.rollback() # Rollback si falla la consulta o el commit de la DB
            print(f"Error CRÍTICO en la tarea delete_old_messages (DB): {e}")