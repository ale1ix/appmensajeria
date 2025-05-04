from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, TextAreaField, SelectField, HiddenField
# Importa los validadores necesarios
from wtforms.validators import DataRequired, Length, EqualTo, Optional, ValidationError

from flask_wtf.file import FileField, FileRequired, FileAllowed
# Importa modelos si necesitas validar contra la base de datos (ej: username único)
from app.models import User, Channel
# Importa el objeto app para acceder a su configuración
from app import app


def coerce_int_or_none(x):
    """Convierte a int, o devuelve None si es '', None, o inválido."""
    if x is None or x == '':
        return None
    try:
        return int(x)
    except (ValueError, TypeError): # Capturar ambos errores
        return None # Devolver None si la conversión falla

# --- Formulario de Inicio de Sesión ---
# Este es el formulario que 'app/routes.py' intentaba importar.
class LoginForm(FlaskForm):
    """Formulario para que los usuarios inicien sesión."""
    # Campo para el nombre de usuario. 'DataRequired' asegura que no esté vacío.
    username = StringField('Usuario', validators=[DataRequired(message="El nombre de usuario es obligatorio.")])
    # Campo para la contraseña.
    password = PasswordField('Contraseña', validators=[DataRequired(message="La contraseña es obligatoria.")])
    # Checkbox opcional para recordar la sesión del usuario.
    remember_me = BooleanField('Recuérdame')
    # Botón para enviar el formulario.
    submit = SubmitField('Iniciar Sesión')

# --- Formularios del Panel de Administración (Ejemplos iniciales) ---

class CreateUserForm(FlaskForm):
    """Formulario para que el admin cree nuevas cuentas de usuario."""
    username = StringField('Nuevo Usuario', validators=[
        DataRequired(message="El nombre de usuario es obligatorio."),
        Length(min=3, max=64, message="El nombre debe tener entre 3 y 64 caracteres.")
    ])
    password = PasswordField('Contraseña', validators=[
        DataRequired(message="La contraseña es obligatoria."),
        Length(min=6, message="La contraseña debe tener al menos 6 caracteres.")
    ])
    # Campo para confirmar la contraseña. 'EqualTo' verifica que coincida con 'password'.
    confirm_password = PasswordField('Confirmar Contraseña', validators=[
        DataRequired(message="Confirma la contraseña."),
        EqualTo('password', message='Las contraseñas deben coincidir.')
    ])
    # Selección de rol para el nuevo usuario.
    role = SelectField('Rol', choices=[('user', 'Usuario'), ('moderator', 'Moderador'), ('admin', 'Administrador')], default='user', validators=[DataRequired()])
    submit = SubmitField('Crear Usuario')

    # Validación personalizada para asegurar que el username no exista ya
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Este nombre de usuario ya está en uso. Por favor, elige otro.')

class CreateChannelForm(FlaskForm):
    """Formulario para que el admin cree nuevos canales."""
    name = StringField('Nombre del Canal', validators=[
        DataRequired(message="El nombre del canal es obligatorio."),
        Length(min=3, max=100)
    ])
    requires_approval = BooleanField('Requerir Aprobación para Unirse', default=False)
    submit = SubmitField('Crear Canal')

    description = TextAreaField('Descripción (Opcional)', validators=[Optional(), Length(max=255)])
    # La contraseña es opcional. Si se pone, se pide confirmación.
    password = PasswordField('Contraseña (Opcional)', validators=[Optional(), Length(min=4)])
    confirm_password = PasswordField('Confirmar Contraseña', validators=[
        EqualTo('password', message='Las contraseñas deben coincidir.')
    ])
    is_writable = BooleanField('Permitir escritura', default=True)
    submit = SubmitField('Crear Canal')

    # Validación personalizada para nombre de canal único
    def validate_name(self, name):
        channel = Channel.query.filter_by(name=name.data).first()
        if channel is not None:
            raise ValidationError('Ya existe un canal con este nombre.')

    # Validación para asegurar que si hay confirmación, también haya contraseña
    def validate_confirm_password(self, confirm_password):
        if confirm_password.data and not self.password.data:
            raise ValidationError('Debes introducir una contraseña si quieres confirmarla.')

class EditChannelForm(FlaskForm):
    """Formulario para que el admin edite un canal existente."""
    name = StringField('Nombre del Canal', validators=[
        DataRequired(message="El nombre del canal es obligatorio."),
        Length(min=3, max=100)
    ])

    requires_approval = BooleanField('Requerir Aprobación para Unirse') # Default se toma del objeto
    submit = SubmitField('Guardar Cambios')

    description = TextAreaField('Descripción (Opcional)', validators=[Optional(), Length(max=255)])
    # Dejamos la contraseña en blanco por defecto. Si se rellena, se cambia.
    password = PasswordField('Nueva Contraseña (Opcional)', validators=[Optional(), Length(min=1)])
    confirm_password = PasswordField('Confirmar Nueva Contraseña', validators=[
        EqualTo('password', message='Las contraseñas deben coincidir.')
    ])
    is_writable = BooleanField('Permitir escritura', default=True)
    # TODO: Añadir requires_approval cuando se implemente en el modelo
    submit = SubmitField('Guardar Cambios')

    # Necesitaremos el ID original para validar el nombre único (excepto él mismo)
    def __init__(self, original_channel_name, *args, **kwargs):
        super(EditChannelForm, self).__init__(*args, **kwargs)
        self.original_channel_name = original_channel_name

    def validate_name(self, name):
        # Si el nombre cambió, verificar que el nuevo nombre no exista ya
        if name.data != self.original_channel_name:
            channel = Channel.query.filter_by(name=name.data).first()
            if channel:
                raise ValidationError('Ya existe un canal con este nombre.')

    # Validar confirmación sólo si se introduce nueva contraseña
    def validate_confirm_password(self, confirm_password):
        if self.password.data and not confirm_password.data:
             raise ValidationError('Debes confirmar la nueva contraseña.')
        if confirm_password.data and not self.password.data:
            # Esto no debería pasar por el EqualTo, pero por si acaso
            pass # O raise ValidationError('Introduce la nueva contraseña si quieres confirmarla.')

class EditUserRoleForm(FlaskForm):
    """Formulario simple para cambiar el rol de un usuario."""
    role = SelectField('Nuevo Rol', choices=[
        ('user', 'Usuario'),
        ('moderator', 'Moderador'),
        ('admin', 'Administrador')
    ], validators=[DataRequired()])
    submit = SubmitField('Actualizar Rol')

class MuteUserForm(FlaskForm):
    user_id = HiddenField()
    # Usar la función de coerción personalizada
    channel_id = SelectField('Canal (Opcional)', coerce=coerce_int_or_none, validators=[Optional()])
    duration = StringField('Duración (ej: 30m, 2h, 1d, never, remove)', default='never', validators=[DataRequired()])
    reason = TextAreaField('Motivo (Opcional)', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Aplicar Mute')

    def __init__(self, *args, **kwargs):
        super(MuteUserForm, self).__init__(*args, **kwargs)
        # Podemos mantener None o usar '', ambos funcionarán con la nueva coerción
        self.channel_id.choices = [(None, '--- Global ---')] + \
                                  [(c.id, c.name) for c in Channel.query.order_by(Channel.name).all()]

class BanUserForm(FlaskForm):
    user_id = HiddenField()
     # Usar la función de coerción personalizada
    channel_id = SelectField('Canal (Opcional)', coerce=coerce_int_or_none, validators=[Optional()])
    duration = StringField('Duración (ej: 1h, 7d, never, remove)', default='never', validators=[DataRequired()])
    reason = TextAreaField('Motivo (Opcional)', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Aplicar Ban')

    def __init__(self, *args, **kwargs):
        super(BanUserForm, self).__init__(*args, **kwargs)
         # Podemos mantener None o usar '', ambos funcionarán con la nueva coerción
        self.channel_id.choices = [(None, '--- Global ---')] + \
                                  [(c.id, c.name) for c in Channel.query.order_by(Channel.name).all()]

class AdminUploadStickerForm(FlaskForm):
    """Formulario para que el admin suba un sticker directamente como aprobado."""
    # Usar las validaciones de Flask-WTF-File
    sticker_file = FileField('Seleccionar Sticker', validators=[
        FileRequired(message='Debes seleccionar un archivo.'),
        # Asegúrate que ALLOWED_EXTENSIONS esté definido en tu Config
        FileAllowed(app.config['ALLOWED_EXTENSIONS'], '¡Solo imágenes (png, jpg, jpeg, gif, webp)!')
    ])
    submit = SubmitField('Subir Sticker Aprobado')

# --- Otros Formularios (Añadir según necesidad) ---
# class BanUserForm(FlaskForm): ...
# class MuteUserForm(FlaskForm): ...
# class UploadStickerForm(FlaskForm): ...
# class MessageForm(FlaskForm): # Podría ser útil para el input de chat si quieres validación extra
#    message = TextAreaField('Mensaje', validators=[DataRequired(), Length(max=5000)])
#    submit = SubmitField('Enviar')