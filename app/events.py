# --- app/events.py ---

from flask import request, session
from flask_socketio import emit, join_room, leave_room, disconnect
from flask_login import current_user
from datetime import datetime, timezone # Asegurar que timezone esté importado

# Importar instancias y modelos
from app import socketio, db
from app.models import User, Channel, Message, Mute, Ban, ChannelJoinRequest, channel_members # Importar Mute y Ban

# --- Gestión de Conexiones ---

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        # Comprobar si está baneado globalmente al conectar (aunque before_request debería pillarlo antes)
        ban = Ban.query.filter_by(user_id=current_user.id, channel_id=None)\
                       .filter((Ban.expires_at == None) | (Ban.expires_at > datetime.now(timezone.utc)))\
                       .first()
        if ban:
            print(f'Cliente baneado intentó conectar: {current_user.username} (SID: {request.sid}). Desconectando.')
            # Podríamos emitir un error específico antes de desconectar
            # emit('error', {'message': 'Tu cuenta está baneada globalmente.'}, to=request.sid)
            disconnect() # Forzar desconexión
            return False # Rechazar conexión persistente

        print(f'Cliente conectado: {request.sid}, Usuario: {current_user.username}')
                # Unir usuario a su propia sala para notificaciones personales
        personal_room = str(current_user.id)
        join_room(personal_room)
        print(f"Usuario {current_user.username} unido a su sala personal: {personal_room}")
    else:
        print(f'Cliente NO AUTENTICADO conectado: {request.sid}.')
        # No autenticados no podrán hacer mucho de todas formas

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Cliente desconectado: {request.sid}')


# --- Gestión de Canales (Salas de SocketIO) ---

@socketio.on('join_channel')
def handle_join_channel(data):
    if not current_user.is_authenticated:
        emit('error', {'message': 'Debes iniciar sesión para unirte a un canal.'}, to=request.sid)
        return

    channel_id = data.get('channel_id')
    if not channel_id:
        print(f"Error: {current_user.username} intentó unirse sin channel_id")
        emit('error', {'message': 'Falta ID del canal.'}, to=request.sid)
        return

    try:
        channel_id = int(channel_id)
    except ValueError:
         print(f"Error: {current_user.username} intentó unirse con channel_id inválido: {data.get('channel_id')}")
         emit('error', {'message': 'ID de canal inválido.'}, to=request.sid)
         return

    channel = Channel.query.get(channel_id)
    if not channel:
        print(f"Error: {current_user.username} intentó unirse a canal inexistente {channel_id}")
        emit('error', {'message': f'Canal {channel_id} no encontrado.'}, to=request.sid)
        return

    # --- Validación de Acceso al Canal (¡Seguridad!) ---
    # 1. Comprobar si está baneado (global O específicamente en este canal)
    now = datetime.now(timezone.utc)
    active_ban = Ban.query.filter_by(user_id=current_user.id)\
                          .filter((Ban.channel_id == channel_id) | (Ban.channel_id == None))\
                          .filter((Ban.expires_at == None) | (Ban.expires_at > now))\
                          .order_by(Ban.channel_id.desc().nullslast())\
                          .first() # Priorizar ban de canal sobre global si ambos existen
    if active_ban:
        scope = f"en '{channel.name}'" if active_ban.channel_id else "globalmente"
        expiry_msg = f" hasta {active_ban.expires_at.strftime('%Y-%m-%d %H:%M')}" if active_ban.expires_at else " permanentemente"
        reason_msg = f" Motivo: {active_ban.reason}" if active_ban.reason else ""
        error_msg = f"No puedes unirte, estás baneado {scope}{expiry_msg}.{reason_msg}"
        print(f"Acceso denegado a canal {channel_id} para {current_user.username} debido a ban ID {active_ban.id}")
        emit('error', {'message': error_msg}, to=request.sid)
        return # Denegar unión

    # 2. TODO: Comprobar si el canal requiere contraseña y si se ha proporcionado
    # 3. TODO: Comprobar si el canal requiere aprobación y si el usuario está aprobado

    # --- Unirse a la sala ---
    room_name = str(channel_id)
    join_room(room_name)
    print(f'Usuario {current_user.username} (SID: {request.sid}) se unió a la sala del canal {channel.name} (ID: {room_name})')

    # Emitir estado actual del canal al usuario que se unió
    emit('channel_status', {
        'channel_id': channel.id,
        'is_writable': channel.is_writable,
        'is_protected': bool(channel.password_hash)
    }, to=request.sid)

    # (Opcional) Emitir un mensaje de sistema al canal indicando que alguien se unió
    system_message = {
        'channel_id': channel.id, # Incluir channel_id para que el JS lo filtre
        'body': f'{current_user.username} se ha unido al canal.',
        'message_type': 'system',
        'timestamp': datetime.now(timezone.utc).isoformat(), # Usar la hora actual en UTC
        'username': 'Sistema'
    }
    emit('new_message', system_message, to=room_name)


@socketio.on('leave_channel')
def handle_leave_channel(data):
    if not current_user.is_authenticated: return
    channel_id = data.get('channel_id')
    if not channel_id: return

    try: # Intentar convertir a int por si acaso
        channel_id = int(channel_id)
        channel = Channel.query.get(channel_id)
        channel_name = channel.name if channel else f"ID {channel_id}"
    except (ValueError, TypeError):
        channel_name = f"ID inválido {data.get('channel_id')}"
        return # Salir si el ID no es válido

    room_name = str(channel_id)
    leave_room(room_name)
    print(f'Usuario {current_user.username} (SID: {request.sid}) salió de la sala del canal {channel_name}')

    # (Opcional) Emitir mensaje de sistema de salida
    system_message = {
        'channel_id': channel_id,
        'body': f'{current_user.username} ha salido del canal.',
        'message_type': 'system',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'username': 'Sistema'
    }
    # Solo emitir si el canal existe realmente
    if channel:
        emit('new_message', system_message, to=room_name)


# --- Envío de Mensajes ---

@socketio.on('send_message')
def handle_send_message(data):
    if not current_user.is_authenticated:
        emit('error', {'message': 'Debes estar logueado para enviar mensajes.'}, to=request.sid)
        return

    channel_id = data.get('channel_id')
    message_body = data.get('body')

    # Validación básica de datos
    if not channel_id or not message_body:
        emit('error', {'message': 'Faltan datos en el mensaje (canal o cuerpo).'}, to=request.sid)
        return
    if len(message_body.strip()) == 0:
         emit('error', {'message': 'El mensaje no puede estar vacío.'}, to=request.sid)
         return
    if len(message_body) > 5000: # Limitar longitud
         emit('error', {'message': 'Mensaje demasiado largo (máx 5000).'}, to=request.sid)
         return

    try:
        channel_id = int(channel_id)
    except ValueError:
         emit('error', {'message': 'ID de canal inválido.'}, to=request.sid)
         return

    channel = Channel.query.get(channel_id)
    if not channel:
        emit('error', {'message': 'El canal no existe.'}, to=request.sid)
        return

    room_name = str(channel_id)
    now = datetime.now(timezone.utc)

    # --- Validación de Permisos (¡Seguridad!) ---

    # 1. ¿Está baneado (global o canal)?
    active_ban = Ban.query.filter_by(user_id=current_user.id)\
                          .filter((Ban.channel_id == channel_id) | (Ban.channel_id == None))\
                          .filter((Ban.expires_at == None) | (Ban.expires_at > now))\
                          .order_by(Ban.channel_id.desc().nullslast())\
                          .first()
    if active_ban:
         scope = f"en '{channel.name}'" if active_ban.channel_id else "globalmente"
         error_msg = f"No puedes enviar mensajes, estás baneado {scope}."
         emit('error', {'message': error_msg}, to=request.sid)
         print(f"Usuario baneado intentó enviar mensaje: {current_user.username} (Ban ID: {active_ban.id})")
         return

    # 2. ¿Está muteado (global o canal)?
    active_mute = Mute.query.filter_by(user_id=current_user.id)\
                           .filter((Mute.channel_id == channel_id) | (Mute.channel_id == None))\
                           .filter((Mute.expires_at == None) | (Mute.expires_at > now))\
                           .order_by(Mute.channel_id.desc().nullslast())\
                           .first()
    if active_mute:
        scope = f"en '{channel.name}'" if active_mute.channel_id else "globalmente"
        reason_msg = f" Motivo: {active_mute.reason}" if active_mute.reason else ""
        error_msg = f"Estás silenciado {scope}. No puedes enviar mensajes.{reason_msg}"
        emit('error', {'message': error_msg}, to=request.sid)
        print(f"Usuario muteado intentó enviar mensaje: {current_user.username} (Mute ID: {active_mute.id})")
        return

    # 3. ¿Está el canal bloqueado para escritura?
    if not channel.is_writable:
         emit('error', {'message': 'El administrador ha desactivado los mensajes en este canal.'}, to=request.sid)
         return

    # --- Guardar Mensaje en BBDD ---
    try:
        # Obtener el tipo de mensaje del cliente, default a 'text' si no se envía
        message_type = data.get('message_type', 'text')
        # Validar el tipo si es necesario (ej. solo permitir 'text', 'image')
        allowed_types = ['text', 'image', 'sticker', 'system'] # Ajusta según tus tipos
        if message_type not in allowed_types:
            message_type = 'text' # O emitir un error

        new_msg = Message(body=message_body,
                        author=current_user,
                        channel=channel,
                        message_type=message_type) # <--- USA EL TIPO RECIBIDO/VALIDADO
        db.session.add(new_msg)
        db.session.commit()

        # --- Emitir Mensaje a la Sala ---
        message_data = {
            'id': new_msg.id,
            'body': new_msg.body,
            'timestamp': new_msg.timestamp.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'), # Ya está en UTC
            'user_id': current_user.id,
            'username': current_user.username,
            'channel_id': channel_id,
            'message_type': new_msg.message_type,
            'is_pinned': new_msg.is_pinned
        }
        emit('new_message', message_data, to=room_name)
        print(f"Mensaje de {current_user.username} enviado al canal {channel.name}: {message_body[:50]}...")

    except Exception as e:
        db.session.rollback()
        print(f"Error al guardar o emitir mensaje: {e}")
        emit('error', {'message': 'Error interno al procesar tu mensaje.'}, to=request.sid)


# --- Indicador de Escritura ---

@socketio.on('typing_started')
def handle_typing_started(data):
    if not current_user.is_authenticated: return
    channel_id = data.get('channel_id')
    if not channel_id: return
    # Podríamos añadir check de mute/ban aquí también si quisiéramos ser estrictos
    room_name = str(channel_id)
    user_info = {'username': current_user.username, 'channel_id': channel_id}
    emit('user_typing', user_info, to=room_name, include_self=False)

@socketio.on('typing_stopped')
def handle_typing_stopped(data):
    if not current_user.is_authenticated: return
    channel_id = data.get('channel_id')
    if not channel_id: return
    room_name = str(channel_id)
    user_info = {'username': current_user.username, 'channel_id': channel_id}
    emit('user_stopped_typing', user_info, to=room_name, include_self=False)

@socketio.on('find_channel_info')
def handle_find_channel_info(data):
    # ... (validaciones iniciales: auth, channel_name) ...
    if not current_user.is_authenticated: return # Cortocircuito si no está autenticado
    channel_name = data.get('channel_name','').strip()
    if not channel_name or len(channel_name) < 3:
        emit('join_channel_feedback', {'error': 'Nombre inválido.'}, to=request.sid); return

    print(f"[DEBUG find_info] User {current_user.username} buscando: '{channel_name}'")
    channel = Channel.query.filter(db.func.lower(Channel.name) == db.func.lower(channel_name)).first()

    if not channel:
        print("[DEBUG find_info] Canal NO encontrado.")
        emit('join_channel_feedback', {'error': f'Canal "{channel_name}" no encontrado.'}, to=request.sid); return

    print(f"[DEBUG find_info] Canal encontrado: ID={channel.id}, Pwd?={bool(channel.password_hash)}, Approval?={channel.requires_approval}")

    # --- Checks Previos ---
    is_member = db.session.query(channel_members).filter_by(user_id=current_user.id, channel_id=channel.id).first()
    if is_member:
        print("[DEBUG find_info] Ya es miembro.")
        emit('join_channel_feedback', {'info': f'Ya eres miembro de "{channel.name}".', 'already_member': True, 'channel_id': channel.id, 'channel_name': channel.name}, to=request.sid); return

    pending_request = ChannelJoinRequest.query.filter_by(user_id=current_user.id, channel_id=channel.id, status='pending').first()
    if pending_request:
        print("[DEBUG find_info] Solicitud pendiente encontrada.")
        emit('join_channel_feedback', {'info': f'Ya tienes solicitud pendiente para "{channel.name}".', 'request_pending': True}, to=request.sid); return

    now = datetime.now(timezone.utc)
    active_ban = Ban.query.filter_by(user_id=current_user.id).filter((Ban.channel_id == channel.id) | (Ban.channel_id == None)).filter((Ban.expires_at == None) | (Ban.expires_at > now)).first()
    if active_ban:
        print("[DEBUG find_info] Usuario BANEADO.")
        emit('join_channel_feedback', {'error': 'No puedes unirte/solicitar, estás baneado.'}, to=request.sid); return
    # --- Fin Checks Previos ---


    # --- Decisión: ¿Unir directo o pedir más info? ---
    # Si NO necesita aprobación Y NO necesita contraseña -> Intentar unir YA MISMO
    if not channel.requires_approval and not channel.password_hash:
        print("[DEBUG find_info] Canal público sin aprobación. Intentando unir directamente...")
        try:
            insert_stmt = channel_members.insert().values(user_id=current_user.id, channel_id=channel.id)
            db.session.execute(insert_stmt); db.session.commit()
            print(f"[DEBUG find_info] ** ÉXITO ** Usuario {current_user.username} unido directamente al canal {channel.name}")
            # --- Acciones post-unión ---
            emit('new_channel_joined', {'id': channel.id, 'name': channel.name}, to=request.sid)
            join_room(str(channel.id))
            emit('channel_status', {'channel_id': channel.id, 'is_writable': channel.is_writable, 'is_protected': False}, to=request.sid)
            system_message = { 'channel_id': channel.id, 'body': f'{current_user.username} se ha unido.', 'message_type': 'system', 'timestamp': now.isoformat(), 'username': 'Sistema'}
            emit('new_message', system_message, to=str(channel.id))
            emit('join_channel_feedback', {'info': f'Te has unido a "{channel.name}".', 'already_member': True, 'channel_id': channel.id, 'channel_name': channel.name }, to=request.sid) # Feedback para cerrar modal
            return # Terminar aquí
        except Exception as e:
             db.session.rollback(); print(f"[DEBUG find_info] Error DB uniendo directo: {e}"); emit('join_channel_feedback', {'error': 'Error al intentar unirse.'}, to=request.sid); return
    else:
        # Si necesita aprobación O contraseña, enviar info al cliente para que continúe
        print("[DEBUG find_info] Canal requiere contraseña o aprobación. Enviando info al cliente.")
        emit('channel_info_found', {
            'channel_id': channel.id,
            'channel_name': channel.name,
            'requires_password': bool(channel.password_hash),
            'requires_approval': channel.requires_approval
        }, to=request.sid)


@socketio.on('attempt_join')
def handle_attempt_join(data):
    # ... (Validaciones iniciales: auth, channel_id, obtener channel) ...
    if not current_user.is_authenticated: return
    channel_id = data.get('channel_id')
    password = data.get('password')
    channel_name = data.get('channel_name', f'ID {channel_id}')
    if not channel_id: emit('join_channel_feedback', {'error': 'Falta ID canal.'}, to=request.sid); return
    try: channel_id = int(channel_id)
    except ValueError: emit('join_channel_feedback', {'error': 'ID canal inválido.'}, to=request.sid); return
    channel = Channel.query.get(channel_id)
    if not channel: emit('join_channel_feedback', {'error': 'Canal no encontrado.'}, to=request.sid); return

    print(f"[DEBUG attempt_join] User {current_user.username} intentando unirse a canal {channel_id} ('{channel_name}'). Pwd: {'Sí' if password else 'No'}")

    # --- Doble Checks ---
    is_member = db.session.query(channel_members).filter_by(user_id=current_user.id, channel_id=channel_id).first()
    if is_member: print("[DEBUG attempt_join] Ya es miembro."); emit('join_channel_feedback', {'info': 'Ya eres miembro.', 'already_member': True, 'channel_id': channel.id, 'channel_name': channel.name}, to=request.sid); return
    now = datetime.now(timezone.utc)
    active_ban = Ban.query.filter_by(user_id=current_user.id).filter((Ban.channel_id == channel.id) | (Ban.channel_id == None)).filter((Ban.expires_at == None) | (Ban.expires_at > now)).first()
    if active_ban: print("[DEBUG attempt_join] Usuario baneado."); emit('join_channel_feedback', {'error': 'No puedes unirte, estás baneado.'}, to=request.sid); return
    # --- Fin Doble Checks ---


    # --- Check Contraseña (SOLO si el canal la requiere) ---
    if channel.password_hash:
        print("[DEBUG attempt_join] Canal requiere contraseña. Verificando...")
        if not password or not channel.check_password(password):
            print("[DEBUG attempt_join] Contraseña INCORRECTA.")
            emit('join_channel_feedback', {'error': 'Contraseña incorrecta.'}, to=request.sid)
            return # Detener si es incorrecta
        print("[DEBUG attempt_join] Contraseña CORRECTA.")
    # --- Fin Check Contraseña ---


    # --- Decisión Final: Unir o Solicitar ---
    # Si llegamos aquí, la contraseña es correcta o no se necesitaba.
    if not channel.requires_approval:
        # --- Unir Directamente ---
        print("[DEBUG attempt_join] Canal no requiere aprobación. Uniendo...")
        try:
            insert_stmt = channel_members.insert().values(user_id=current_user.id, channel_id=channel.id)
            db.session.execute(insert_stmt); db.session.commit()
            print(f"[DEBUG attempt_join] ** ÉXITO ** Usuario {current_user.username} unido al canal {channel.name}")
            # --- Acciones post-unión ---
            emit('new_channel_joined', {'id': channel.id, 'name': channel.name}, to=request.sid)
            join_room(str(channel.id))
            emit('channel_status', {'channel_id': channel.id, 'is_writable': channel.is_writable, 'is_protected': bool(channel.password_hash)}, to=request.sid)
            system_message = { 'channel_id': channel.id, 'body': f'{current_user.username} se ha unido.', 'message_type': 'system', 'timestamp': now.isoformat(), 'username': 'Sistema'}
            emit('new_message', system_message, to=str(channel.id))
            emit('join_channel_feedback', {'info': f'Te has unido a "{channel.name}".', 'already_member': True, 'channel_id': channel.id, 'channel_name': channel.name }, to=request.sid) # Feedback para cerrar modal
        except Exception as e:
             db.session.rollback(); print(f"[DEBUG attempt_join] Error DB uniendo: {e}"); emit('join_channel_feedback', {'error': 'Error al intentar unirse.'}, to=request.sid)
    else:
        # --- Requiere Aprobación -> Crear Solicitud ---
        print("[DEBUG attempt_join] Canal requiere aprobación. Creando solicitud...")
        existing_request = ChannelJoinRequest.query.filter_by(user_id=current_user.id, channel_id=channel.id, status='pending').first()
        if existing_request:
             print("[DEBUG attempt_join] Solicitud ya pendiente.")
             emit('join_channel_feedback', {'info': 'Ya tienes una solicitud pendiente.', 'request_pending': True}, to=request.sid); return
        try:
            new_request = ChannelJoinRequest(user_id=current_user.id, channel_id=channel.id)
            db.session.add(new_request); db.session.commit()
            print(f"[DEBUG attempt_join] ** ÉXITO ** Creada solicitud user {current_user.id} -> canal {channel.id}")
            emit('join_channel_feedback', {'success': f'Solicitud enviada para "{channel.name}".'}, to=request.sid)
        except Exception as e:
             if "UNIQUE constraint failed" in str(e):
                  print(f"[DEBUG attempt_join] Solicitud ya existía (error UNIQUE).")
                  emit('join_channel_feedback', {'info': 'Ya has enviado una solicitud para este canal.'}, to=request.sid)
             else:
                 db.session.rollback(); print(f"[DEBUG attempt_join] Error DB creando request: {e}"); emit('join_channel_feedback', {'error': 'Error al enviar solicitud.'}, to=request.sid)

@socketio.on('self_leave_channel')
def handle_self_leave(data):
    """Usuario solicita salir de un canal."""
    if not current_user.is_authenticated: return
    channel_id = data.get('channel_id')
    if not channel_id: return

    try:
        channel_id = int(channel_id)
        channel = Channel.query.get(channel_id)
        if not channel: return # Canal no existe

        # Eliminar de channel_members
        delete_members_stmt = channel_members.delete().where(
            (channel_members.c.user_id == current_user.id) &
            (channel_members.c.channel_id == channel_id)
        )
        result = db.session.execute(delete_members_stmt)

        # --- NUEVO: Eliminar solicitudes de unión asociadas ---
        deleted_requests_count = ChannelJoinRequest.query.filter_by(
            user_id=current_user.id,
            channel_id=channel_id
        ).delete()
        # -----------------------------------------------------

        db.session.commit() # Hacer commit DESPUÉS de ambas eliminaciones

        if result.rowcount > 0 or deleted_requests_count > 0: # Si se eliminó membresía O solicitud
            print(f"Usuario {current_user.username} salió del canal {channel.name} (Miembro: {result.rowcount}, Solicitudes: {deleted_requests_count})")
            # Notificar al propio usuario
            emit('left_channel_successfully', {'channel_id': channel_id}, to=request.sid)
            # Abandonar la sala SocketIO
            room_name = str(channel_id)
            leave_room(room_name)
            # Emitir mensaje de sistema al canal (solo si era miembro)
            if result.rowcount > 0:
                system_message = { 'channel_id': channel_id, 'body': f'{current_user.username} ha salido del canal.', 'message_type': 'system', 'timestamp': datetime.now(timezone.utc).isoformat(), 'username': 'Sistema'}
                emit('new_message', system_message, to=room_name)
        else:
            print(f"Usuario {current_user.username} intentó salir de canal {channel.name} pero no era miembro ni tenía solicitudes.")

    except Exception as e:
        db.session.rollback()
        print(f"Error en self_leave_channel user {current_user.id}, channel {channel_id}: {e}")
        emit('error', {'message': 'Error al intentar salir del canal.'}, to=request.sid)

@socketio.on('join_channel_with_password')
def handle_join_channel_password(data):
    """Intenta unir a un usuario a un canal protegido usando contraseña."""
    # --- Validaciones iniciales ---
    if not current_user.is_authenticated:
        emit('error', {'message': 'Autenticación requerida.'}, to=request.sid); return
    channel_id = data.get('channel_id')
    password = data.get('password')
    if not channel_id or password is None:
        emit('error', {'message': 'Faltan datos (ID de canal o contraseña).'}, to=request.sid); return
    try: channel_id = int(channel_id)
    except ValueError:
         emit('error', {'message': 'ID de canal inválido.'}, to=request.sid); return
    channel = Channel.query.get(channel_id)
    if not channel:
        emit('error', {'message': f'Canal {channel_id} no encontrado.'}, to=request.sid); return
    # --- Fin Validaciones ---

    now = datetime.now(timezone.utc)
    password_check_passed = False # Flag para saber si pasamos la validación de contraseña

    # 1. Validar Contraseña si el canal la requiere
    if channel.password_hash:
        if not channel.check_password(password):
            print(f"Contraseña INCORRECTA para user {current_user.username} en canal {channel_id}")
            emit('error', {'message': f'Contraseña incorrecta para el canal "{channel.name}".'}, to=request.sid)
            return # Salir si es incorrecta
        else:
            print(f"Contraseña correcta para user {current_user.username} en canal {channel_id}")
            password_check_passed = True # Marcamos que la contraseña es correcta
    else:
        # Si el canal ya no tiene contraseña, consideramos que la validación pasó
        print(f"Canal {channel_id} no requiere contraseña (intento de unión con pwd).")
        password_check_passed = True

    # Si llegamos aquí, la contraseña es correcta o no era necesaria (password_check_passed es True)

    # 2. Validar Ban
    active_ban = Ban.query.filter_by(user_id=current_user.id)\
                          .filter((Ban.channel_id == channel_id) | (Ban.channel_id == None))\
                          .filter((Ban.expires_at == None) | (Ban.expires_at > now)).first()
    if active_ban:
        emit('error', {'message': 'No puedes unirte, estás baneado.'}, to=request.sid)
        return

    # 3. Validar Aprobación (Solo si el canal la requiere Y el usuario NO es miembro aún)
    is_member = db.session.query(channel_members).filter_by(
        user_id=current_user.id, channel_id=channel_id
    ).first()

    if channel.requires_approval and not is_member:
        # Si requiere aprobación y NO es miembro, no puede unirse directamente aquí.
        emit('error', {'message': 'Este canal requiere aprobación previa.'}, to=request.sid)
        return

    # --- Si todas las validaciones pasan (Contraseña/Ban/Aprobación) ---

    # 4. Añadir a miembros SI NO LO ERA YA
    user_was_added_now = False
    if not is_member:
        try:
            insert_stmt = channel_members.insert().values(user_id=current_user.id, channel_id=channel.id)
            db.session.execute(insert_stmt)
            db.session.commit()
            user_was_added_now = True
            print(f"Usuario {current_user.username} añadido a miembros de canal {channel_id} (password OK / no pwd needed)")
        except Exception as e:
            db.session.rollback(); print(f"Error DB añadiendo miembro (pwd ok): {e}")
            emit('error', {'message': 'Error al intentar unirse.'}, to=request.sid)
            return # Falló la adición a la DB, no continuar
    else:
         print(f"Usuario {current_user.username} ya era miembro del canal {channel_id} (pwd ok / no pwd needed).")

    # 5. Unir a la sala de SocketIO y Emitir eventos de confirmación al CLIENTE
    # Esto se hace SIEMPRE que las validaciones pasen, sea miembro nuevo o existente.
    try:
        room_name = str(channel_id)
        join_room(room_name)
        print(f'Usuario {current_user.username} unido/re-unido a sala {room_name}')

        # Emitir eventos CLAVE para que el cliente actualice la UI
        emit('new_channel_joined', {'id': channel.id, 'name': channel.name}, to=request.sid)
        emit('channel_status', {'channel_id': channel.id, 'is_writable': channel.is_writable, 'is_protected': bool(channel.password_hash)}, to=request.sid)
        socketio.emit('request_history', {'channel_id': channel.id}, to=request.sid) # Pedir historial

        # Opcional: Mensaje de sistema (quizás solo si se añadió ahora?)
        if user_was_added_now:
             system_message = { 'channel_id': channel.id, 'body': f'{current_user.username} se ha unido.', 'message_type': 'system', 'timestamp': now.isoformat(), 'username': 'Sistema'}
             emit('new_message', system_message, to=room_name)

    except Exception as e:
         print(f"Error al unirse a sala o emitir confirmación (pwd ok): {e}")
         # No hacer rollback aquí, la adición a la DB (si ocurrió) ya está hecha.
         emit('error', {'message': 'Error al finalizar la conexión al canal.'}, to=request.sid)

# --- Carga de Historial ---

@socketio.on('request_history')
def handle_request_history(data):
    if not current_user.is_authenticated:
        emit('error', {'message': 'Autenticación requerida.'}, to=request.sid)
        return
    channel_id = data.get('channel_id')
    if not channel_id:
        emit('error', {'message': 'Falta channel_id para pedir historial.'}, to=request.sid)
        return
    try:
        channel_id = int(channel_id)
        channel = Channel.query.get(channel_id)
        if not channel:
             emit('error', {'message': f'Canal {channel_id} no encontrado.'}, to=request.sid)
             return

        # Validar acceso (ban) ANTES de enviar historial
        now = datetime.now(timezone.utc)
        active_ban = Ban.query.filter_by(user_id=current_user.id)\
                              .filter((Ban.channel_id == channel_id) | (Ban.channel_id == None))\
                              .filter((Ban.expires_at == None) | (Ban.expires_at > now))\
                              .first()
        if active_ban:
            emit('error', {'message': 'No puedes ver el historial, estás baneado.'}, to=request.sid)
            return

        print(f"Usuario {current_user.username} solicitó historial del canal {channel.name}")
        messages = Message.query.filter_by(channel_id=channel_id).order_by(Message.timestamp.asc()).all()
        messages_data = [
            {
                'id': msg.id, 'body': msg.body, 'timestamp': msg.timestamp.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
                'user_id': msg.author.id, 'username': msg.author.username,
                'message_type': msg.message_type, 'is_pinned': msg.is_pinned
            } for msg in messages
        ]
        emit('channel_history', {'channel_id': channel_id, 'messages': messages_data}, to=request.sid)
        print(f"Historial de {len(messages_data)} mensajes enviado a {current_user.username}")

    except ValueError:
         emit('error', {'message': 'ID de canal inválido.'}, to=request.sid)
    except Exception as e:
        print(f"Error al obtener historial para canal {channel_id}: {e}")
        emit('error', {'message': 'Error interno al obtener el historial.'}, to=request.sid)