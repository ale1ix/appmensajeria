# --- app/routes.py ---

from flask import render_template, flash, redirect, url_for, request, abort, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from urllib.parse import urlparse # Para redirección segura
from functools import wraps
from datetime import datetime, timedelta, timezone
import re # Para parsear duración
from werkzeug.utils import secure_filename
import os
import uuid


# Importar instancias globales y modelos/formularios
from app import app, db, socketio
from app.models import User, Channel, Message, Mute, Ban, ChannelJoinRequest, channel_members, Setting, Sticker
from app.forms import (
    LoginForm, CreateChannelForm, EditChannelForm,
    CreateUserForm, EditUserRoleForm, MuteUserForm, BanUserForm, AdminUploadStickerForm 
)


# --- FUNCIÓN AUXILIAR PARA EXTENSIONES ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# --- Decoradores de Control de Acceso ---

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def moderator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_moderator:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# --- Comprobación Global de Ban (antes de cada petición) ---

@app.before_request # <-- ASEGÚRATE DE QUE ESTE DECORADOR ESTÉ AQUÍ
def before_request_checks():
    # --- Check Mantenimiento (Se ejecuta primero) ---
    maint_setting = Setting.query.filter_by(key='site_closed').first()
    is_site_closed = maint_setting.value.lower() == 'true' if maint_setting else False

    allowed_while_closed = ['static', 'login', 'logout', 'maintenance_page', 'banned_page']
    is_admin_access = current_user.is_authenticated and current_user.is_admin

    # Si está cerrado Y NO eres admin O estás intentando acceder a algo no permitido: redirigir
    if is_site_closed and not is_admin_access and request.endpoint not in allowed_while_closed:
         # print(f"DEBUG: Redirigiendo a mantenimiento. Endpoint: {request.endpoint}") # DEBUG opcional
         return redirect(url_for('maintenance_page'))
    # Si está cerrado PERO ERES ADMIN, la ejecución continúa hacia el check de ban

    # --- Check Ban Global (Se ejecuta si el sitio está abierto o eres admin) ---
    allowed_endpoints_ban = ['static', 'logout', 'login', 'banned_page', 'maintenance_page']
    # Si quieres permitir a admins baneados acceder al panel, añádelo aquí:
    # if is_admin_access: allowed_endpoints_ban.extend(['admin_dashboard', 'admin_apply_ban', ...])

    # Comprobar solo si está autenticado y el endpoint no es uno de los siempre permitidos
    if current_user.is_authenticated and request.endpoint not in allowed_endpoints_ban:
        ban = Ban.query.filter_by(user_id=current_user.id, channel_id=None)\
                       .filter((Ban.expires_at == None) | (Ban.expires_at > datetime.now(timezone.utc)))\
                       .first()
        if ban:
            # Redirigir a la página de baneo (evitar bucle si ya está allí)
            if request.endpoint != 'banned_page':
                 # print(f"DEBUG: Redirigiendo a banned. Endpoint: {request.endpoint}") # DEBUG opcional
                 flash("Tu cuenta está baneada globalmente.", "danger")
                 # logout_user() # Opcional
                 return redirect(url_for('banned_page'))
    # --- Fin Check Ban Global ---

    # Si no se retornó ninguna redirección, la petición continúa normalmente.)

# --- Añadir Ruta para Página de Mantenimiento ---
@app.route('/maintenance') # <-- ¡AÑADIR ESTA LÍNEA!
def maintenance_page():
    # Verificar si el sitio realmente está cerrado (por si alguien llega directo a la URL)
    maint_setting = Setting.query.filter_by(key='site_closed').first()
    is_site_closed = maint_setting.value.lower() == 'true' if maint_setting else False
    # Si el sitio está abierto Y no soy admin, redirigir a index
    if not is_site_closed and not (current_user.is_authenticated and current_user.is_admin):
        return redirect(url_for('index'))
    # Renderizar la plantilla de mantenimiento
    return render_template('maintenance.html', title='Mantenimiento')

# --- Ruta para la Página de Baneo ---

@app.route('/banned')
def banned_page():
    if not current_user.is_authenticated:
         return redirect(url_for('login')) # Si no está logueado, al login

    # Verificar si realmente tiene un ban global activo
    ban = Ban.query.filter_by(user_id=current_user.id, channel_id=None)\
                   .filter((Ban.expires_at == None) | (Ban.expires_at > datetime.now(timezone.utc)))\
                   .first()
    if not ban:
         # Si no está baneado, fuera de aquí
         return redirect(url_for('index'))

    # Mostrar la página de baneo
    return render_template('banned.html', title='Baneado', ban=ban)


# --- Rutas Principales ---

@app.route('/')
@app.route('/index')
@login_required
def index():
    """Página principal - Muestra la interfaz de chat con los canales del usuario."""
    now = datetime.now(timezone.utc) # Necesitamos la hora actual
    try:
        # --- INICIO DEL BLOQUE A MODIFICAR / REEMPLAZAR ---

        # Obtener IDs de los canales donde el usuario actual tiene un ban ACTIVO específico de canal
        banned_channel_ids_query = db.session.query(Ban.channel_id).filter(
            Ban.user_id == current_user.id,
            Ban.channel_id != None, # Solo bans específicos de canal
            (Ban.expires_at == None) | (Ban.expires_at > now)
        )
        banned_channel_ids = [item[0] for item in banned_channel_ids_query.all()]

        # Obtener los canales aprobados para el usuario usando la relación
        # y FILTRAR los baneados si es necesario
        query = current_user.approved_channels # Empezamos con la relación

        if banned_channel_ids:
             # Excluir los canales baneados
             query = query.filter(Channel.id.notin_(banned_channel_ids))

        # Ejecutar la consulta final ordenada por nombre
        user_channels = query.order_by(Channel.name).all()

        # --- FIN DEL BLOQUE A MODIFICAR / REEMPLAZAR ---

        # Check de Ban Global (mantenemos por seguridad)
        global_ban = Ban.query.filter_by(user_id=current_user.id, channel_id=None)\
                               .filter((Ban.expires_at == None) | (Ban.expires_at > now))\
                               .first()
        if global_ban:
            user_channels = [] # No mostrar canales si hay ban global
            flash("Tu cuenta está baneada globalmente.", "danger")

    except Exception as e:
        flash(f"Error al cargar tus canales: {e}", "danger")
        print(f"Error DB al cargar canales para usuario {current_user.id}: {e}")
        user_channels = [] # Asegurar que sea una lista vacía en caso de error

    # Pasar SOLO la lista 'user_channels' (filtrada) a la plantilla
    return render_template('chat_interface.html', title='Chat', channels=user_channels)

# --- Rutas de Autenticación ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Usuario o contraseña inválidos', 'danger')
            return redirect(url_for('login'))

        # Comprobar si está baneado globalmente ANTES de loguear
        ban = Ban.query.filter_by(user_id=user.id, channel_id=None)\
                       .filter((Ban.expires_at == None) | (Ban.expires_at > datetime.now(timezone.utc)))\
                       .first()
        if ban:
             flash('Tu cuenta está baneada globalmente. No puedes iniciar sesión.', 'danger')
             return redirect(url_for('login')) # De vuelta al login

        login_user(user, remember=form.remember_me.data)
        flash(f'¡Inicio de sesión exitoso como {user.username}!', 'success')
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Iniciar Sesión', form=form)

@app.route('/logout')
def logout():
    logout_user()
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('login'))

# --- Rutas API Chat (Ejemplo) ---

@app.route('/get_channel_messages/<int:channel_id>')
@login_required
def get_channel_messages(channel_id):
    """Devuelve mensajes (usado por SocketIO ahora, esta ruta puede ser obsoleta o para carga inicial AJAX)."""
    channel = Channel.query.get_or_404(channel_id)
    # TODO: Añadir check de contraseña/acceso aquí si es necesario

    messages = Message.query.filter_by(channel_id=channel.id).order_by(Message.timestamp.asc()).all()
    messages_data = [
        {
            'id': msg.id, 'body': msg.body, 'timestamp': msg.timestamp.isoformat() + 'Z',
            'user_id': msg.author.id, 'username': msg.author.username,
            'message_type': msg.message_type, 'is_pinned': msg.is_pinned
        } for msg in messages
    ]
    return jsonify(messages_data)


# --- Rutas del Panel de Administración ---

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    """Muestra el panel de control principal del admin con listas y formularios de modal."""
    now = datetime.now(timezone.utc)
    try:
        users = User.query.order_by(User.username).all()
        channels = Channel.query.order_by(Channel.name).all()

        # --- OBTENER MUTES/BANS ACTIVOS ---
        active_mutes_list = Mute.query.filter(
            (Mute.expires_at == None) | (Mute.expires_at > now)
        ).all()
        active_bans_list = Ban.query.filter(
            (Ban.expires_at == None) | (Ban.expires_at > now)
        ).all()

        # Crear diccionarios para acceso rápido en la plantilla:
        # { user_id: [(channel_id_or_None, mute_object), ...], ... }
        active_mutes = {}
        for mute in active_mutes_list:
            if mute.user_id not in active_mutes:
                active_mutes[mute.user_id] = []
            active_mutes[mute.user_id].append((mute.channel_id, mute))

        active_bans = {}
        for ban in active_bans_list:
            if ban.user_id not in active_bans:
                active_bans[ban.user_id] = []
            active_bans[ban.user_id].append((ban.channel_id, ban))
        # --- FIN OBTENER MUTES/BANS ---

        pending_sticker_count = Sticker.query.filter_by(is_approved=False).count() # Contar pendientes

    except Exception as e:
        flash(f"Error al cargar datos para el panel: {e}", "danger")
        print(f"Error DB al cargar dashboard: {e}")
        users = []
        channels = []
        active_mutes = {}
        active_bans = {}
        pending_sticker_count = 0

    mute_form = MuteUserForm()
    ban_form = BanUserForm()

    # --- OBTENER ESTADO MANTENIMIENTO ---
    site_closed_setting = Setting.query.filter_by(key='site_closed').first()
    is_site_closed = site_closed_setting.value.lower() == 'true' if site_closed_setting else False
    # --- FIN OBTENER ESTADO ---

    return render_template('admin_panel.html', title='Panel Admin',
                           users=users, channels=channels,
                           mute_form=mute_form, ban_form=ban_form,
                           active_mutes=active_mutes, active_bans=active_bans,
                           is_site_closed=is_site_closed, 
                           pending_sticker_count=pending_sticker_count) # <-- Pasar diccionarios

# --- Rutas Gestión Canales ---

@app.route('/admin/create-channel', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_create_channel():
    form = CreateChannelForm()
    if form.validate_on_submit():
        new_channel = Channel(name=form.name.data,
                              description=form.description.data,
                              is_writable=form.is_writable.data)
        if form.password.data:
            new_channel.set_password(form.password.data)
        try:
            db.session.add(new_channel)
            db.session.commit()
            flash(f'Canal "{new_channel.name}" creado exitosamente!', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el canal: {e}', 'danger')
            print(f"Error DB al crear canal: {e}")
    return render_template('admin_create_channel.html', title='Crear Canal', form=form)

@app.route('/admin/edit-channel/<int:channel_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_channel(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    form = EditChannelForm(original_channel_name=channel.name, obj=channel)

    if form.validate_on_submit():
        channel.name = form.name.data
        channel.description = form.description.data
        channel.is_writable = form.is_writable.data
        channel.requires_approval = form.requires_approval.data # Asegúrate que este campo esté en el form

        # --- SOLO establecer contraseña SI se proporcionó una nueva ---
        if form.password.data:
            print(f"[DEBUG edit_channel POST] Se proporcionó nueva contraseña. Aplicando hash.")
            channel.set_password(form.password.data)
        else:
             print(f"[DEBUG edit_channel POST] Campo contraseña vacío. NO se cambia el hash existente.")
        # --------------------------------------------------------------

        try:
            # No hace falta db.session.add(channel) si lo obtuviste de la DB,
            # SQLAlchemy rastrea los cambios. Pero no hace daño.
            db.session.add(channel)
            db.session.commit()
            print(f"[DEBUG edit_channel POST] Commit realizado. Hash final: {channel.password_hash}")
            flash(f'Canal "{channel.name}" actualizado exitosamente!', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar el canal: {e}', 'danger')
            print(f"Error DB al editar canal {channel_id}: {e}")
            print(f"[DEBUG edit_channel POST Error] Hash antes rollback: {channel.password_hash}")
    elif request.method == 'POST':
        print(f"[DEBUG edit_channel POST] Formulario inválido: {form.errors}")
    else: # GET request
        print(f"[DEBUG edit_channel GET] Cargando canal {channel_id}. Hash actual: {channel.password_hash}")

    return render_template('admin_edit_channel.html', title='Editar Canal', form=form, channel=channel)

@app.route('/admin/delete-channel/<int:channel_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_channel(channel_id):
    channel_to_delete = Channel.query.get_or_404(channel_id)
    channel_name = channel_to_delete.name
    try:
        # Borrar bans/mutes asociados a este canal ANTES de borrar el canal
        Mute.query.filter_by(channel_id=channel_id).delete()
        Ban.query.filter_by(channel_id=channel_id).delete()
        # Borrar canal (y mensajes por cascade)
        db.session.delete(channel_to_delete)
        db.session.commit()
        flash(f'Canal "{channel_name}" y todos sus mensajes/bans/mutes asociados han sido eliminados.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el canal "{channel_name}": {e}', 'danger')
        print(f"Error DB al eliminar canal {channel_id}: {e}")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle-channel-write/<int:channel_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_channel_write(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    try:
        channel.is_writable = not channel.is_writable
        db.session.add(channel)
        db.session.commit()
        estado = "habilitada" if channel.is_writable else "deshabilitada"
        flash(f'La escritura en el canal "{channel.name}" ha sido {estado}.', 'success')
        # Notificar a clientes
        room_name = str(channel.id)
        socketio.emit('channel_status_update', {
            'channel_id': channel.id,
            'is_writable': channel.is_writable
        }, to=room_name)
        print(f"Emitido channel_status_update para canal {channel.id}, writable: {channel.is_writable}")
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado de escritura del canal "{channel.name}": {e}', 'danger')
        print(f"Error DB al cambiar escritura canal {channel_id}: {e}")
    return redirect(url_for('admin_dashboard'))


# --- Rutas Gestión Usuarios ---

@app.route('/admin/create-user', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        new_user = User(username=form.username.data, role=form.role.data)
        new_user.set_password(form.password.data)
        try:
            db.session.add(new_user)
            db.session.commit()
            flash(f'Usuario "{new_user.username}" ({new_user.role}) creado exitosamente!', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el usuario: {e}', 'danger')
            print(f"Error DB al crear usuario: {e}")
    return render_template('admin_create_user.html', title='Crear Usuario', form=form)

@app.route('/admin/edit-user-role/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user_role(user_id):
    if user_id == current_user.id:
        flash('No puedes cambiar tu propio rol.', 'warning')
        return redirect(url_for('admin_dashboard'))
    if user_id == 1: # Proteger admin principal
        flash('No se puede cambiar el rol del administrador principal.', 'danger')
        return redirect(url_for('admin_dashboard'))

    user = User.query.get_or_404(user_id)
    form = EditUserRoleForm(obj=user)
    if form.validate_on_submit():
        new_role = form.role.data
        user.role = new_role
        try:
            db.session.add(user)
            db.session.commit()
            flash(f'Rol del usuario "{user.username}" actualizado a "{new_role}".', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
             db.session.rollback()
             flash(f'Error al actualizar rol de "{user.username}": {e}', 'danger')
             print(f"Error DB al editar rol usuario {user_id}: {e}")
    return render_template('admin_edit_user_role.html', title='Editar Rol', form=form, user=user)


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    if current_user.id == user_id:
         flash('No puedes eliminar tu propia cuenta de administrador.', 'danger')
         return redirect(url_for('admin_dashboard'))
    if user_id == 1: # Proteger admin principal
        flash('No se puede eliminar al administrador principal (ID 1).', 'danger')
        return redirect(url_for('admin_dashboard'))

    user_to_delete = User.query.get_or_404(user_id)
    username = user_to_delete.username
    try:
        # Borrar Mutes y Bans donde este usuario es el afectado O el admin que lo aplicó
        Mute.query.filter((Mute.user_id == user_id) | (Mute.admin_id == user_id)).delete()
        Ban.query.filter((Ban.user_id == user_id) | (Ban.admin_id == user_id)).delete()
        # ¡Ojo! Mensajes quedan huérfanos (ForeignKey ON DELETE no configurado por defecto en SQLite)
        # Podrías añadir lógica para reasignarlos a un usuario "Eliminado" o borrarlos manualmente.
        # Message.query.filter_by(user_id=user_id).delete() # Descomentar si quieres borrar mensajes
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'Usuario "{username}" y sus mutes/bans asociados eliminados exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el usuario "{username}": {e}', 'danger')
        print(f"Error DB al eliminar usuario {user_id}: {e}")
    return redirect(url_for('admin_dashboard'))


# --- Rutas para Aplicar/Remover Mute/Ban ---

def parse_duration(duration_str):
    """Parsea duración y devuelve datetime de expiración, None (permanente), 'remove', o False (error)."""
    if not isinstance(duration_str, str): return False # Añadir check de tipo
    duration_str = duration_str.lower().strip()
    if duration_str == 'never': return None
    if duration_str == 'remove': return 'remove'
    match = re.fullmatch(r'(\d+)\s*([mhd])', duration_str) # Permitir espacio opcional
    if not match: return False
    try:
        value = int(match.group(1))
        unit = match.group(2)
        now = datetime.now(timezone.utc)
        if unit == 'm': return now + timedelta(minutes=value)
        if unit == 'h': return now + timedelta(hours=value)
        if unit == 'd': return now + timedelta(days=value)
        return False
    except ValueError: # Por si el número es demasiado grande
        return False


@app.route('/admin/apply-mute', methods=['POST'])
@login_required
@admin_required
def admin_apply_mute():
    form = MuteUserForm()
    user_id_str = form.user_id.data
    # --- VALIDACIONES INICIALES ---
    if not user_id_str:
         flash('Falta ID de usuario.', 'danger'); return redirect(url_for('admin_dashboard'))
    try:
        user_id = int(user_id_str)
        if user_id == current_user.id:
            flash('No puedes silenciar tu propia cuenta.', 'warning'); return redirect(url_for('admin_dashboard'))
        if user_id == 1: # Proteger admin principal
            flash('No se puede silenciar al administrador principal.', 'danger'); return redirect(url_for('admin_dashboard'))
    except ValueError:
        flash('ID de usuario inválido.', 'danger'); return redirect(url_for('admin_dashboard'))
    # --- FIN VALIDACIONES ---
    user = User.query.get_or_404(user_id)

    # Usamos validate() en lugar de validate_on_submit() porque no hay token CSRF explícito en el modal por defecto
    # Si habilitas CSRF globalmente, necesitarás pasar {{ mute_form.csrf_token }} en el modal
    if form.validate():
        channel_id = form.channel_id.data # Ya es None o int por coerce
        duration_input = form.duration.data
        reason = form.reason.data if form.reason.data else None
        expires_at = parse_duration(duration_input)

        if expires_at is False:
            flash('Formato de duración inválido. Usa ej: 30m, 2h, 1d, never, remove.', 'danger')
        else:
            try:
                existing_mute = Mute.query.filter_by(user_id=user_id, channel_id=channel_id).first()
                if expires_at == 'remove':
                    if existing_mute:
                        db.session.delete(existing_mute); db.session.commit()
                        scope = f"en canal ID {channel_id}" if channel_id else "global"
                        flash(f'Mute para "{user.username}" {scope} eliminado.', 'success')
                    else: flash(f'No se encontró un mute activo para "{user.username}" en ese ámbito.', 'warning')
                elif existing_mute:
                    existing_mute.expires_at = expires_at; existing_mute.reason = reason
                    existing_mute.admin_id = current_user.id; existing_mute.created_at = datetime.now(timezone.utc)
                    db.session.add(existing_mute); db.session.commit()
                    expiry_msg = f"hasta {expires_at.strftime('%Y-%m-%d %H:%M')}" if expires_at else "permanentemente"
                    scope = f"en canal ID {channel_id}" if channel_id else "global"
                    flash(f'Mute para "{user.username}" {scope} actualizado ({expiry_msg}).', 'success')
                else: # Crear nuevo
                    if expires_at == 'remove': # No crear si se intentó remover uno inexistente
                         flash(f'No se encontró un mute activo para "{user.username}" en ese ámbito para remover.', 'warning')
                    else:
                        new_mute = Mute(user_id=user_id, admin_id=current_user.id, channel_id=channel_id, reason=reason, expires_at=expires_at)
                        db.session.add(new_mute); db.session.commit()
                        expiry_msg = f"hasta {expires_at.strftime('%Y-%m-%d %H:%M')}" if expires_at else "permanentemente"
                        scope = f"en canal ID {channel_id}" if channel_id else "global"
                        flash(f'Usuario "{user.username}" silenciado {scope} ({expiry_msg}).', 'success')
            except Exception as e:
                db.session.rollback(); flash(f'Error al procesar mute: {e}', 'danger'); print(f"Error DB apply mute: {e}")
    else:
        # Mostrar errores de validación del formulario
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error en campo '{getattr(form, field).label.text}': {error}", 'danger')

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/apply-ban', methods=['POST'])
@login_required
@admin_required
def admin_apply_ban():
    form = BanUserForm()
    user_id_str = form.user_id.data
    # --- VALIDACIONES INICIALES ---
    if not user_id_str:
         flash('Falta ID de usuario.', 'danger'); return redirect(url_for('admin_dashboard'))
    try:
        user_id = int(user_id_str)
        if user_id == current_user.id:
            flash('No puedes banear tu propia cuenta.', 'warning'); return redirect(url_for('admin_dashboard'))
        if user_id == 1: # Proteger admin principal
            flash('No se puede banear al administrador principal.', 'danger'); return redirect(url_for('admin_dashboard'))
    except ValueError:
        flash('ID de usuario inválido.', 'danger'); return redirect(url_for('admin_dashboard'))
    # --- FIN VALIDACIONES ---
    user = User.query.get_or_404(user_id)

    if form.validate(): # Usar validate() para modales sin CSRF explícito
        channel_id = form.channel_id.data
        duration_input = form.duration.data
        reason = form.reason.data if form.reason.data else None
        expires_at = parse_duration(duration_input)

        if expires_at is False:
            flash('Formato de duración inválido. Usa ej: 1h, 7d, never, remove.', 'danger')
        else:
            try:
                existing_ban = Ban.query.filter_by(user_id=user_id, channel_id=channel_id).first()
                if expires_at == 'remove':
                    if existing_ban:
                        db.session.delete(existing_ban); db.session.commit()
                        scope = f"en canal ID {channel_id}" if channel_id else "global"
                        flash(f'Ban para "{user.username}" {scope} eliminado.', 'success')
                    else: flash(f'No se encontró un ban activo para "{user.username}" en ese ámbito.', 'warning')
                elif existing_ban:
                    existing_ban.expires_at = expires_at; existing_ban.reason = reason
                    existing_ban.admin_id = current_user.id; existing_ban.created_at = datetime.now(timezone.utc)
                    db.session.add(existing_ban); db.session.commit()
                    expiry_msg = f"hasta {expires_at.strftime('%Y-%m-%d %H:%M')}" if expires_at else "permanentemente"
                    scope = f"en canal ID {channel_id}" if channel_id else "global"
                    flash(f'Ban para "{user.username}" {scope} actualizado ({expiry_msg}).', 'success')
                else: # Crear nuevo
                    if expires_at == 'remove':
                         flash(f'No se encontró un ban activo para "{user.username}" en ese ámbito para remover.', 'warning')
                    else:
                        new_ban = Ban(user_id=user_id, admin_id=current_user.id, channel_id=channel_id, reason=reason, expires_at=expires_at)
                        db.session.add(new_ban); db.session.commit()
                        expiry_msg = f"hasta {expires_at.strftime('%Y-%m-%d %H:%M')}" if expires_at else "permanentemente"
                        scope = f"en canal ID {channel_id}" if channel_id else "global"
                        flash(f'Usuario "{user.username}" baneado {scope} ({expiry_msg}).', 'success')
            except Exception as e:
                db.session.rollback(); flash(f'Error al procesar ban: {e}', 'danger'); print(f"Error DB apply ban: {e}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error en campo '{getattr(form, field).label.text}': {error}", 'danger')

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/pending-requests')
@login_required
@admin_required # O @moderator_required si los mods pueden aprobar
def admin_pending_requests():
    """Muestra las solicitudes pendientes para unirse a canales."""
    try:
# En app/routes.py, dentro de admin_pending_requests
        pending_requests = ChannelJoinRequest.query.filter_by(status='pending').order_by(ChannelJoinRequest.requested_at.asc()).all()
        print(f"--- DEBUG pending_requests: Encontradas {len(pending_requests)} solicitudes pendientes.") # DEBUG
        # Pre-cargar datos relacionados para eficiencia en la plantilla (opcional pero bueno)
        # from sqlalchemy.orm import joinedload
        # pending_requests = ChannelJoinRequest.query.options(joinedload(ChannelJoinRequest.user), joinedload(ChannelJoinRequest.channel))\
        #                                            .filter_by(status='pending')\
        #                                            .order_by(ChannelJoinRequest.requested_at.asc()).all()
    except Exception as e:
         flash(f"Error al cargar solicitudes pendientes: {e}", "danger")
         print(f"Error DB al cargar pending requests: {e}")
         pending_requests = []

    return render_template('admin_pending_requests.html', title='Solicitudes Pendientes', requests=pending_requests)


@app.route('/admin/approve-request/<int:request_id>', methods=['POST'])
@login_required
@admin_required # O @moderator_required
def admin_approve_request(request_id):
    """Aprueba una solicitud pendiente."""
    join_request = ChannelJoinRequest.query.get_or_404(request_id)

    if join_request.status != 'pending':
        flash('Esta solicitud ya ha sido procesada.', 'warning')
        return redirect(url_for('admin_pending_requests'))

    try:
        # Cambiar estado de la solicitud
        join_request.status = 'approved'
        join_request.reviewed_by_admin_id = current_user.id
        join_request.reviewed_at = datetime.now(timezone.utc)

        # Añadir usuario a la tabla de miembros del canal (si no está ya)
        # Comprobación extra por si acaso
        is_already_member = db.session.query(channel_members).filter_by(
             user_id=join_request.user_id,
             channel_id=join_request.channel_id
         ).first()

        if not is_already_member:
             # Usar la relación es más SQLAlchemy-style, pero una inserción directa también funciona
             # join_request.channel.approved_members.append(join_request.user)
             # O inserción directa:
             insert_stmt = channel_members.insert().values(
                 user_id=join_request.user_id,
                 channel_id=join_request.channel_id
             )
             db.session.execute(insert_stmt)

        db.session.add(join_request) # Guardar cambios en la solicitud
        db.session.commit()

        flash(f'Solicitud de {join_request.user.username} para unirse a "{join_request.channel.name}" aprobada.', 'success')

        # --- Notificar al usuario ---
        # Necesitamos una forma de enviar a un user_id específico. Unirse a room personal en connect.
        target_room = str(join_request.user_id)
        socketio.emit('request_approved', {
            'message': f'Tu solicitud para unirte a "{join_request.channel.name}" ha sido aprobada.',
            'channel_id': join_request.channel_id,
            'channel_name': join_request.channel.name
        }, to=target_room)
        print(f"Emitido request_approved a room {target_room}")

    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar la solicitud: {e}', 'danger')
        print(f"Error DB al aprobar request {request_id}: {e}")

    return redirect(url_for('admin_pending_requests'))


@app.route('/admin/reject-request/<int:request_id>', methods=['POST'])
@login_required
@admin_required # O @moderator_required
def admin_reject_request(request_id):
    """Rechaza una solicitud pendiente."""
    join_request = ChannelJoinRequest.query.get_or_404(request_id)

    if join_request.status != 'pending':
        flash('Esta solicitud ya ha sido procesada.', 'warning')
        return redirect(url_for('admin_pending_requests'))

    try:
        join_request.status = 'rejected'
        join_request.reviewed_by_admin_id = current_user.id
        join_request.reviewed_at = datetime.now(timezone.utc)
        db.session.add(join_request)
        db.session.commit()
        flash(f'Solicitud de {join_request.user.username} para unirse a "{join_request.channel.name}" rechazada.', 'info')

        # --- Notificar al usuario ---
        target_room = str(join_request.user_id)
        socketio.emit('request_rejected', {
             'message': f'Tu solicitud para unirte a "{join_request.channel.name}" ha sido rechazada.',
             'channel_id': join_request.channel_id,
             'channel_name': join_request.channel.name
        }, to=target_room)
        print(f"Emitido request_rejected a room {target_room}")

    except Exception as e:
        db.session.rollback()
        flash(f'Error al rechazar la solicitud: {e}', 'danger')
        print(f"Error DB al rechazar request {request_id}: {e}")

    return redirect(url_for('admin_pending_requests'))


@app.route('/admin/kick-user/<int:user_id>/channel/<int:channel_id>', methods=['POST'])
@login_required
@admin_required # O @moderator_required
def admin_kick_user_from_channel(user_id, channel_id):
    """Elimina a un usuario de la tabla channel_members y sus solicitudes de unión para ese canal."""
    # Validaciones iniciales (no kickearse a sí mismo, no kickear admin 1)
    if user_id == current_user.id:
        flash("No puedes kickearte a ti mismo.", "warning"); return redirect(url_for('admin_dashboard'))
    if user_id == 1:
         flash("No puedes kickear al administrador principal.", "danger"); return redirect(url_for('admin_dashboard'))

    user = User.query.get_or_404(user_id)
    channel = Channel.query.get_or_404(channel_id)

    try:
        # Eliminar la entrada en la tabla de asociación (miembros)
        delete_members_stmt = channel_members.delete().where(
            (channel_members.c.user_id == user_id) &
            (channel_members.c.channel_id == channel_id)
        )
        result = db.session.execute(delete_members_stmt)

        # --- NUEVO: Eliminar solicitudes de unión asociadas ---
        deleted_requests_count = ChannelJoinRequest.query.filter_by(
            user_id=user_id,
            channel_id=channel_id
        ).delete()
        # -----------------------------------------------------

        db.session.commit() # Hacer commit DESPUÉS de ambas eliminaciones

        if result.rowcount > 0 or deleted_requests_count > 0:
            flash(f'Usuario "{user.username}" kickeado del canal "{channel.name}". Sus solicitudes de unión para este canal también fueron eliminadas.', 'success')
            # --- Notificar al usuario kickeado y a la sala ---
            room_name = str(channel_id)
            personal_room = str(user_id)
            kick_message = f'Has sido kickeado del canal "{channel.name}" por {current_user.username}.'
            socketio.emit('kicked_from_channel', {
                'message': kick_message,
                'channel_id': channel_id
            }, to=personal_room)
            # Notificar al resto del canal (si era miembro)
            if result.rowcount > 0:
                system_message = { 'channel_id': channel_id, 'body': f'{user.username} ha sido kickeado del canal por {current_user.username}.', 'message_type': 'system', 'timestamp': datetime.now(timezone.utc).isoformat(), 'username': 'Sistema'}
                socketio.emit('new_message', system_message, to=room_name)
            # Forzar desconexión de la sala SocketIO (implementación simple - ver comentarios anteriores)
            # ... (código opcional para buscar SID y llamar a socketio.leave_room) ...
        else:
             flash(f'El usuario "{user.username}" no era miembro ni tenía solicitudes pendientes/pasadas para el canal "{channel.name}".', 'info')

    except Exception as e:
         db.session.rollback()
         flash(f'Error al kickear usuario: {e}', 'danger')
         print(f"Error DB kick user {user_id} from channel {channel_id}: {e}")

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle-maintenance', methods=['POST'])
@login_required
@admin_required
def admin_toggle_maintenance():
    """Activa o desactiva el modo mantenimiento."""
    setting_key = 'site_closed'
    try:
        # Buscar la configuración existente o crearla si no existe
        setting = Setting.query.filter_by(key=setting_key).first()
        if not setting:
            # Si no existe, la creamos como 'False' (abierto) por defecto
            current_state = False
            setting = Setting(key=setting_key, value=str(current_state))
            db.session.add(setting)
            # No hacemos commit aún, lo haremos después de cambiar el estado
        else:
            # Convertir valor guardado (string) a booleano
            current_state = setting.value.lower() == 'true'

        # Cambiar el estado
        new_state = not current_state
        setting.value = str(new_state) # Guardar como string 'True' o 'False'
        db.session.add(setting) # Marcar para guardar
        db.session.commit()

        estado_msg = "activado" if new_state else "desactivado"
        flash(f'Modo mantenimiento {estado_msg}.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar modo mantenimiento: {e}', 'danger')
        print(f"Error DB toggle maintenance: {e}")

    return redirect(url_for('admin_dashboard'))

# --- RUTA /upload-media ---
@app.route('/upload-media', methods=['POST'])
@login_required
def upload_media():
    """
    Maneja la subida de archivos:
    - Imágenes directas al chat (requiere channel_id).
    - Stickers enviados por usuarios para aprobación.
    """
    if 'media_file' not in request.files:
        print("[DEBUG upload_media] Error: No 'media_file' in request.files")
        return jsonify({'error': 'No se encontró el archivo en la solicitud.'}), 400

    file = request.files['media_file']
    # Obtener datos del formulario
    # Convertir a booleano de forma segura
    is_sticker_submission_str = request.form.get('is_sticker_submission', 'false')
    is_sticker_submission = is_sticker_submission_str.lower() == 'true'
    channel_id = request.form.get('channel_id') # Puede ser None si es sticker

    print(f"[DEBUG upload_media] Recibido: filename='{file.filename}', is_sticker={is_sticker_submission}, channel_id={channel_id}")

    if file.filename == '':
        print("[DEBUG upload_media] Error: Filename vacío.")
        return jsonify({'error': 'No se seleccionó ningún archivo.'}), 400

    # Validar extensión y archivo
    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        extension = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{extension}"
        print(f"[DEBUG upload_media] Archivo válido: '{original_filename}', guardando como '{unique_filename}'")

        # --- LÓGICA PARA SUBIDA DE STICKER POR USUARIO (PARA APROBACIÓN) ---
        if is_sticker_submission:
            pending_folder_rel = 'pending_stickers' # Carpeta relativa dentro de 'uploads'
            target_folder_abs = os.path.join(app.config['UPLOAD_FOLDER'], pending_folder_rel)
            # Ruta relativa completa para guardar en la DB (respecto a 'static')
            db_path = os.path.join('uploads', pending_folder_rel, unique_filename).replace('\\', '/')
            save_path_abs = os.path.join(target_folder_abs, unique_filename)
            success_message = "Sticker enviado para aprobación."

            try:
                os.makedirs(target_folder_abs, exist_ok=True) # Crear carpeta si no existe
                file.save(save_path_abs)
                print(f"[DEBUG upload_media] Sticker PENDIENTE guardado físicamente en: {save_path_abs}")

                # Crear registro en BBDD para sticker pendiente
                new_sticker = Sticker(uploader_user_id=current_user.id,
                                      file_path=db_path, # Guardar ruta relativa correcta (uploads/pending_stickers/...)
                                      is_approved=False) # ¡IMPORTANTE! Marcar como no aprobado
                db.session.add(new_sticker)
                db.session.commit()
                print(f"[DEBUG upload_media] Sticker PENDIENTE registrado en DB: ID {new_sticker.id}, Ruta DB: {db_path}")

                return jsonify({'message': success_message}), 200

            except Exception as e:
                db.session.rollback()
                print(f"[ERROR upload_media] Procesando subida de sticker PENDIENTE: {e}")
                # Intentar borrar archivo si falla el registro en DB
                if os.path.exists(save_path_abs):
                    try: os.remove(save_path_abs)
                    except OSError as rm_err: print(f"Error al eliminar archivo PENDIENTE temporal: {rm_err}")
                return jsonify({'error': f'Error interno al guardar sticker pendiente: {e}'}), 500

        # --- LÓGICA PARA SUBIDA DE IMAGEN DIRECTA AL CHAT ---
        else:
            # Validar que se proporcionó channel_id
            if not channel_id:
                print("[DEBUG upload_media] Error: Falta channel_id para imagen directa.")
                return jsonify({'error': 'Falta ID del canal para enviar la imagen.'}), 400

            # Validar channel_id y obtener canal
            try:
                channel_id_int = int(channel_id)
                channel = Channel.query.get(channel_id_int)
                if not channel:
                     print(f"[DEBUG upload_media] Error: Canal no encontrado ID: {channel_id_int}")
                     return jsonify({'error': 'Canal no encontrado.'}), 404
            except ValueError:
                 print(f"[DEBUG upload_media] Error: ID de canal inválido: {channel_id}")
                 return jsonify({'error': 'ID de canal inválido.'}), 400

            # Comprobar permisos para enviar a este canal (ban, mute, writable)
            now = datetime.now(timezone.utc)
            active_ban = Ban.query.filter_by(user_id=current_user.id)\
                                  .filter((Ban.channel_id == channel_id_int) | (Ban.channel_id == None))\
                                  .filter((Ban.expires_at == None) | (Ban.expires_at > now)).first()
            if active_ban:
                print(f"[DEBUG upload_media] Denegado: Usuario {current_user.id} baneado en canal {channel_id_int} o global.")
                return jsonify({'error': 'No puedes enviar imágenes, estás baneado.'}), 403

            active_mute = Mute.query.filter_by(user_id=current_user.id)\
                                   .filter((Mute.channel_id == channel_id_int) | (Mute.channel_id == None))\
                                   .filter((Mute.expires_at == None) | (Mute.expires_at > now)).first()
            if active_mute:
                 print(f"[DEBUG upload_media] Denegado: Usuario {current_user.id} muteado en canal {channel_id_int} o global.")
                 return jsonify({'error': 'No puedes enviar imágenes, estás silenciado.'}), 403

            if not channel.is_writable:
                 print(f"[DEBUG upload_media] Denegado: Canal {channel_id_int} no es escribible.")
                 return jsonify({'error': 'Este canal no permite enviar mensajes/imágenes.'}), 403
            # Fin comprobación permisos

            # Definir carpetas y rutas para imagen directa
            image_folder_rel = 'images' # Carpeta relativa dentro de 'uploads'
            target_folder_abs = os.path.join(app.config['UPLOAD_FOLDER'], image_folder_rel)
             # Ruta relativa para guardar en DB y construir URL (respecto a 'static')
            db_path = os.path.join('uploads', image_folder_rel, unique_filename).replace('\\', '/')
            # Construir la URL relativa que usará el cliente y se guardará en el mensaje
            image_url = url_for('static', filename=db_path) # Ej: /static/uploads/images/uuid.jpg
            save_path_abs = os.path.join(target_folder_abs, unique_filename)
            success_message = "Imagen enviada."

            try:
                os.makedirs(target_folder_abs, exist_ok=True)
                file.save(save_path_abs)
                print(f"[DEBUG upload_media] Imagen directa guardada físicamente en: {save_path_abs}")

                # Crear mensaje de tipo imagen y emitirlo
                new_msg = Message(body=image_url, # Guardar URL relativa generada por url_for
                                  author=current_user,
                                  channel_id=channel_id_int,
                                  message_type='image') # Correcto
                db.session.add(new_msg)
                db.session.commit()
                print(f"[DEBUG upload_media] Mensaje de imagen registrado en DB: ID {new_msg.id}, URL: {image_url}, Canal: {channel_id_int}")

                # Emitir a la sala
                message_data = {
                    'id': new_msg.id,
                    'body': image_url, # Enviar URL relativa
                    'timestamp': new_msg.timestamp.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'channel_id': channel_id_int,
                    'message_type': 'image',
                    'is_pinned': False
                }
                socketio.emit('new_message', message_data, to=str(channel_id_int))
                print(f"[DEBUG upload_media] Emitido 'new_message' (imagen) a sala {channel_id_int}")

                return jsonify({'message': success_message, 'image_url': image_url}), 200

            except Exception as e:
                db.session.rollback()
                print(f"[ERROR upload_media] Procesando subida de imagen directa: {e}")
                if os.path.exists(save_path_abs):
                    try: os.remove(save_path_abs)
                    except OSError as rm_err: print(f"Error al eliminar archivo de imagen directo: {rm_err}")
                return jsonify({'error': f'Error interno al guardar la imagen: {e}'}), 500

    else: # Si el tipo de archivo no es permitido
        print(f"[DEBUG upload_media] Error: Tipo de archivo no permitido: '{file.filename}'")
        return jsonify({'error': 'Tipo de archivo no permitido.'}), 400


@app.route('/get-approved-stickers')
@login_required
def get_approved_stickers():
    """Devuelve una lista de URLs de stickers aprobados."""
    try:
        approved_stickers = Sticker.query.filter_by(is_approved=True).order_by(Sticker.id).all()
        sticker_data = [
            {
                'id': sticker.id,
                # sticker.file_path debe ser como 'uploads/stickers/filename.png'
                'url': url_for('static', filename=sticker.file_path)
            }
            for sticker in approved_stickers
        ]
        return jsonify(sticker_data)
    except Exception as e:
        print(f"Error al obtener stickers aprobados: {e}")
        return jsonify({"error": "No se pudieron cargar los stickers."}), 500


# --- Ruta Aprobar (Se mantiene, pero ahora redirige a 'manage_stickers') ---
@app.route('/admin/approve-sticker/<int:sticker_id>', methods=['POST'])
@login_required
@admin_required
def admin_approve_sticker(sticker_id):
    """Aprueba un sticker pendiente, lo mueve y actualiza la BBDD."""
    # ... (La lógica interna de mover archivo y actualizar DB es la misma) ...
    sticker = Sticker.query.get_or_404(sticker_id)
    if sticker.is_approved:
        flash('Este sticker ya estaba aprobado.', 'info')
        return redirect(url_for('admin_manage_stickers')) # <-- REDIRIGIR A NUEVA PÁGINA

    old_db_path = sticker.file_path
    filename = os.path.basename(old_db_path)
    new_db_path = os.path.join('uploads', 'stickers', filename).replace('\\', '/')
    old_fs_path = os.path.join(app.static_folder, old_db_path)
    new_fs_path = os.path.join(app.static_folder, new_db_path)
    new_folder_fs = os.path.dirname(new_fs_path)

    try:
        os.makedirs(new_folder_fs, exist_ok=True)
        if os.path.exists(old_fs_path):
             os.rename(old_fs_path, new_fs_path)
             print(f"Sticker movido de {old_fs_path} a {new_fs_path}")
        else:
             raise FileNotFoundError(f"Archivo pendiente no encontrado en: {old_fs_path}")

        sticker.is_approved = True
        sticker.file_path = new_db_path # Guardar la nueva ruta relativa
        db.session.add(sticker)
        db.session.commit()
        flash(f'Sticker ID {sticker.id} aprobado.', 'success')

    except FileNotFoundError as fnf_error:
         db.session.rollback()
         flash(str(fnf_error), 'danger')
         print(f"Error al aprobar sticker {sticker_id}: {fnf_error}")
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar sticker: {e}', 'danger')
        print(f"Error al aprobar sticker {sticker_id}: {e}")

    return redirect(url_for('admin_manage_stickers')) # <-- REDIRIGIR A NUEVA PÁGINA


@app.route('/admin/reject-sticker/<int:sticker_id>', methods=['POST'])
@login_required
@admin_required
def admin_reject_sticker(sticker_id):
    """Rechaza y elimina un sticker pendiente."""
    sticker = Sticker.query.get_or_404(sticker_id)
    if sticker.is_approved:
        flash('Este sticker ya estaba aprobado (no se puede rechazar).', 'warning')
        return redirect(url_for('admin_approve_stickers'))

    # Ruta física del archivo a eliminar
    fs_path_to_delete = os.path.join(app.static_folder, sticker.file_path)

    try:
        # 1. Eliminar registro de la BBDD
        db.session.delete(sticker)
        # 2. Eliminar el archivo físico
        if os.path.exists(fs_path_to_delete):
            os.remove(fs_path_to_delete)
            print(f"Archivo de sticker rechazado eliminado: {fs_path_to_delete}")
        else:
             print(f"WARN: Archivo no encontrado para eliminar en {fs_path_to_delete} para sticker rechazado {sticker.id}")
             # Consideramos esto un éxito parcial, el registro se elimina igual

        db.session.commit() # Commit DEPUÉS de intentar borrar el archivo
        flash(f'Sticker ID {sticker.id} rechazado y eliminado.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al rechazar sticker: {e}', 'danger')
        print(f"Error al rechazar sticker {sticker_id}: {e}")

    return redirect(url_for('admin_approve_stickers'))

# --- NUEVA Ruta: Gestionar Stickers (Mostrar Todos + Form Subida Admin) ---
@app.route('/admin/manage-stickers', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_manage_stickers():
    """Muestra todos los stickers (pendientes y aprobados) y permite subida directa."""
    upload_form = AdminUploadStickerForm() # Formulario para subida directa

    # --- Lógica POST para Subida Directa del Admin ---
    if upload_form.validate_on_submit():
        file = upload_form.sticker_file.data
        if file:
            try:
                original_filename = secure_filename(file.filename)
                extension = original_filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{extension}"

                # Guardar directamente en la carpeta de stickers APROBADOS
                approved_folder_rel = 'stickers'
                target_folder_abs = os.path.join(app.config['UPLOAD_FOLDER'], approved_folder_rel)
                # Ruta para DB: uploads/stickers/filename.ext
                db_path = os.path.join('uploads', approved_folder_rel, unique_filename).replace('\\', '/')
                save_path_abs = os.path.join(target_folder_abs, unique_filename)

                os.makedirs(target_folder_abs, exist_ok=True)
                file.save(save_path_abs)
                print(f"Sticker APROBADO subido por admin guardado en: {save_path_abs}")

                # Crear registro en BBDD directamente como APROBADO
                new_sticker = Sticker(uploader_user_id=current_user.id, # Guardar quién lo subió
                                      file_path=db_path,
                                      is_approved=True) # <--- Marcar como True
                db.session.add(new_sticker)
                db.session.commit()
                print(f"Sticker APROBADO registrado en DB: ID {new_sticker.id}, Ruta DB: {db_path}")
                flash('Sticker subido y aprobado exitosamente!', 'success')

            except Exception as e:
                db.session.rollback()
                flash(f'Error al subir sticker: {e}', 'danger')
                print(f"Error subiendo sticker (admin): {e}")
                # Intentar borrar archivo si falla la DB?
                if 'save_path_abs' in locals() and os.path.exists(save_path_abs):
                    try: os.remove(save_path_abs)
                    except OSError as rm_err: print(f"Error eliminando archivo tras fallo DB: {rm_err}")

            # Redirigir siempre para evitar reenvío del formulario al recargar
            return redirect(url_for('admin_manage_stickers'))
        else:
             # Esto no debería pasar si FileRequired funciona, pero por si acaso
             flash('No se seleccionó ningún archivo.', 'warning')
             return redirect(url_for('admin_manage_stickers'))
    elif request.method == 'POST':
        # Si el form no es válido en POST (ej: tipo archivo incorrecto)
        # Los errores se mostrarán automáticamente por flash o junto al campo
        flash('Error en el formulario de subida.', 'danger')
        # No redirigimos, dejamos que se re-renderice la plantilla con los errores

    # --- Lógica GET (Mostrar todos los stickers) ---
    try:
        # Obtener todos, ordenando aprobados primero, luego por fecha
        all_stickers = Sticker.query.options(db.joinedload(Sticker.uploader))\
                                    .order_by(Sticker.is_approved.desc(), Sticker.uploaded_at.asc()).all()
    except Exception as e:
         flash(f"Error al cargar stickers: {e}", "danger")
         print(f"Error DB al cargar manage stickers: {e}")
         all_stickers = []

    # Pasar formulario y stickers a la plantilla
    return render_template('admin_manage_stickers.html',
                           title='Gestionar Stickers',
                           stickers=all_stickers,
                           form=upload_form) # Pasar instancia del form

# --- NUEVA Ruta Unificada para Borrar Stickers ---
@app.route('/admin/delete-sticker/<int:sticker_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_sticker(sticker_id):
    """Elimina un sticker (pendiente o aprobado), su archivo y registro DB."""
    sticker = Sticker.query.get_or_404(sticker_id)
    sticker_path = sticker.file_path # Ej: uploads/pending_stickers/.. o uploads/stickers/..
    sticker_status = "aprobado" if sticker.is_approved else "pendiente"

    # Ruta física del archivo a eliminar (relativa a app/static)
    fs_path_to_delete = os.path.join(app.static_folder, sticker_path)

    try:
        # 1. Eliminar registro de la BBDD
        db.session.delete(sticker)

        # 2. Eliminar el archivo físico
        if os.path.exists(fs_path_to_delete):
            os.remove(fs_path_to_delete)
            print(f"Archivo de sticker ({sticker_status}) eliminado: {fs_path_to_delete}")
        else:
             print(f"WARN: Archivo no encontrado para eliminar en {fs_path_to_delete} para sticker {sticker_id}")

        db.session.commit()
        flash(f'Sticker ID {sticker_id} ({sticker_status}) eliminado exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar sticker: {e}', 'danger')
        print(f"Error al eliminar sticker {sticker_id}: {e}")

    # Redirigir de vuelta a la página de gestión
    return redirect(url_for('admin_manage_stickers'))


# --- Manejadores de Errores ---
# (Mismos que antes: 403, 404, 500)

@app.errorhandler(403)
def forbidden_error(error):
    return "<h1>403 - Acceso Prohibido</h1><p>No tienes permiso para acceder a esta página.</p><a href='/'>Volver</a>", 403

@app.errorhandler(404)
def not_found_error(error):
     return "<h1>404 - Página No Encontrada</h1><p>La página que buscas no existe.</p><a href='/'>Volver</a>", 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    print(f"Internal Server Error: {error}") # Loggear el error real
    # Intentar importar traceback para log más detallado
    try:
        import traceback
        print(traceback.format_exc())
    except ImportError:
        pass
    return "<h1>500 - Error Interno del Servidor</h1><p>Algo salió mal. Inténtalo de nuevo más tarde.</p><a href='/'>Volver</a>", 500