from datetime import datetime, timezone # Usamos timezone para asegurar UTC
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin # Mixin especial para modelos de usuario con Flask-Login
from app import db, login # Importamos la instancia db y login desde app/__init__.py
from sqlalchemy import Index # Importamos Index para definir índices personalizados

# --- User Loader para Flask-Login ---
# Flask-Login necesita saber cómo cargar un usuario dado su ID (que almacena en la sesión).
# Este decorador registra la función 'load_user' con Flask-Login.
@login.user_loader
def load_user(id):
    # Convierte el ID (que viene como string de la sesión) a entero y busca en la BBDD.
    return User.query.get(int(id))

channel_members = db.Table('channel_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('channel_id', db.Integer, db.ForeignKey('channel.id'), primary_key=True)
)

# --- Modelo User ---
# Hereda de db.Model (clase base de SQLAlchemy para modelos) y UserMixin.
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True) # Clave primaria autoincremental
    username = db.Column(db.String(64), index=True, unique=True, nullable=False) # Nombre de usuario, indexado y único
    password_hash = db.Column(db.String(256), nullable=False) # Hash de la contraseña (NUNCA la contraseña real)
    role = db.Column(db.String(10), index=True, default='user', nullable=False) # Roles: 'user', 'moderator', 'admin'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Fecha de creación (UTC)

    # Relación uno-a-muchos con Message: Un usuario puede escribir muchos mensajes.
    # backref='author' crea un atributo virtual 'author' en el modelo Message.
    # lazy='dynamic' significa que los mensajes no se cargan automáticamente, sino que se obtiene un objeto query.
    messages = db.relationship('Message', backref='author', lazy='dynamic', cascade='all, delete-orphan')

    # Relación muchos-a-muchos con Channel (si decides implementarla - más complejo)
    # channels = db.relationship('Channel', secondary=user_channels, back_populates='users')

    # --- Métodos para Contraseñas (¡Seguridad!) ---
    def set_password(self, password):
        """Genera un hash seguro para la contraseña y lo guarda."""
        # Usamos un método de hash fuerte con sal (salt) incluida.
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica si la contraseña proporcionada coincide con el hash almacenado."""
        return check_password_hash(self.password_hash, password)

    approved_channels = db.relationship(
        'Channel', secondary=channel_members,
        backref=db.backref('approved_members', lazy='dynamic'),
        lazy='dynamic'
    )

    # --- Propiedades para Roles (Conveniencia) ---
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_moderator(self):
        # Un admin también es considerado moderador en términos de permisos base.
        return self.role == 'moderator' or self.role == 'admin'

    def __repr__(self):
        """Representación textual del objeto User, útil para depuración."""
        return f'<User {self.username} (ID: {self.id}, Role: {self.role})>'

# --- Modelo Channel ---
class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), index=True, unique=True, nullable=False) # Nombre del canal, único
    description = db.Column(db.String(255), nullable=True) # Descripción opcional
    password_hash = db.Column(db.String(256), nullable=True) # Hash si el canal tiene contraseña
    is_writable = db.Column(db.Boolean, default=True, nullable=False) # Control admin para permitir/denegar mensajes
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Fecha creación (UTC)
    requires_approval = db.Column(db.Boolean, default=False, nullable=False)
    # Relación uno-a-muchos con Message: Un canal contiene muchos mensajes.
    # cascade='all, delete-orphan' significa que si se borra un canal, se borran todos sus mensajes.
    messages = db.relationship('Message', backref='channel', lazy='dynamic', cascade='all, delete-orphan')

    # --- Métodos para Contraseña del Canal ---
    def set_password(self, password):
        """Establece o elimina la contraseña del canal."""
        if password:
            self.password_hash = generate_password_hash(password)
        else:
            self.password_hash = None # Sin contraseña

    def check_password(self, password):
        """Verifica la contraseña introducida contra el hash del canal."""
        if not self.password_hash:
            # Si el canal no tiene contraseña, consideramos cualquier intento como válido.
            # O podrías devolver False si quieres forzar a que no se pueda 'acertar' una contraseña vacía.
            return True
        if not password: # Si se proporciona una contraseña vacía a un canal protegido
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<Channel {self.name} (ID: {self.id})>'

class ChannelJoinRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # Estado: 'pending', 'approved', 'rejected'
    status = db.Column(db.String(10), default='pending', nullable=False, index=True)
    # Quién y cuándo revisó (opcional)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # Relaciones
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('join_requests', lazy='dynamic'))
    channel = db.relationship('Channel', backref=db.backref('join_requests', lazy='dynamic', cascade='all, delete-orphan')) # Borrar requests si se borra el canal
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_admin_id])

    # Restricción única para evitar múltiples solicitudes pendientes del mismo usuario/canal
    __table_args__ = (db.UniqueConstraint('user_id', 'channel_id', name='uq_user_channel_join_request'),)

    def __repr__(self):
         return f'<JoinRequest ID {self.id} User {self.user_id} -> Channel {self.channel_id} ({self.status})>'

# --- Modelo Message ---
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False) # Contenido (texto, ruta a imagen/sticker, o data del mensaje de sistema)
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.now(timezone.utc)) # Fecha mensaje (UTC)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Quién lo envió (Clave foránea a User.id)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False) # Dónde se envió (Clave foránea a Channel.id)
    message_type = db.Column(db.String(10), default='text', nullable=False) # 'text', 'image', 'sticker', 'system'
    is_pinned = db.Column(db.Boolean, default=False, nullable=False) # Para mensajes fijados por admin/mod

    def __repr__(self):
        return f'<Message {self.id} ({self.message_type}) in C:{self.channel_id} by U:{self.user_id}>'


# --- Modelos Adicionales (Añadir más tarde cuando se implementen) ---

class Sticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uploader_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_path = db.Column(db.String(255), unique=True, nullable=False) # Ruta relativa al archivo
    is_approved = db.Column(db.Boolean, default=False, index=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
     # Relación para acceder al usuario que lo subió
    uploader = db.relationship('User')
    def __repr__(self):
         return f'<Sticker {self.id} Approved: {self.is_approved}>'

# --- Modelo Ban ---
class Ban(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # Usuario baneado
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Admin que aplicó el ban
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=True, index=True) # Null si es global
    reason = db.Column(db.String(255), nullable=True) # Motivo opcional
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True, index=True) # Null si es permanente

    # Relaciones para fácil acceso (opcional pero útil)
    banned_user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('bans_received', lazy='dynamic'))
    banning_admin = db.relationship('User', foreign_keys=[admin_id], backref=db.backref('bans_issued', lazy='dynamic'))
    banned_in_channel = db.relationship('Channel', backref=db.backref('bans', lazy='dynamic'))

    def __repr__(self):
        scope = f"en canal {self.channel_id}" if self.channel_id else "globalmente"
        expiry = f"hasta {self.expires_at.strftime('%Y-%m-%d %H:%M')}" if self.expires_at else "permanentemente"
        return f'<Ban ID {self.id} en User {self.user_id} {scope}, {expiry}>'

# --- Modelo Mute ---
class Mute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # Usuario silenciado
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Admin que aplicó el mute
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=True, index=True) # Null si es global
    reason = db.Column(db.String(255), nullable=True) # Motivo opcional
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True, index=True) # Null si es permanente

    # Relaciones
    muted_user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('mutes_received', lazy='dynamic'))
    muting_admin = db.relationship('User', foreign_keys=[admin_id], backref=db.backref('mutes_issued', lazy='dynamic'))
    muted_in_channel = db.relationship('Channel', backref=db.backref('mutes', lazy='dynamic'))

    def __repr__(self):
        scope = f"en canal {self.channel_id}" if self.channel_id else "globalmente"
        expiry = f"hasta {self.expires_at.strftime('%Y-%m-%d %H:%M')}" if self.expires_at else "permanentemente"
        return f'<Mute ID {self.id} en User {self.user_id} {scope}, {expiry}>'

class Setting(db.Model): # Para ajustes globales como el cierre del sitio
    id = db.Column(db.Integer, primary_key=True) # Podría ser solo una fila
    key = db.Column(db.String(50), unique=True, nullable=False, index=True) # ej: 'site_closed'
    value = db.Column(db.String(255)) # ej: 'True' / 'False'
    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'