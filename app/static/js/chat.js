// --- app/static/js/chat.js (v5 - Final Corregida) ---

// --- Variables Globales ---
const socket = io(); // Conexión Socket.IO
let currentChannelId = null; // ID del canal activo
let currentChannelName = null; // Nombre del canal activo (para confirmación de salida)
let typingTimer = null; // Timer para 'typing_stopped'
const typingTimeout = 1500; // ms
let isTyping = false; // Flag para estado de escritura local
const usersTyping = {}; // Objeto para rastrear quién escribe { channel_id: { username: true } }
let currentChannelIsWritable = false; // Estado de escritura del canal actual
let foundChannelInfo = null; // Guarda la info del canal encontrado en el modal de unión
// USERNAME_GLOBAL se define en un <script> en chat_interface.html ANTES de este archivo
let mediaPopoverInstance = null;
let unreadCounts = {}; // <<< --- NUEVO: Objeto para contadores { channel_id: count }
let originalTitle = document.title; // <<< --- NUEVO: Guardar título original

// --- Manejadores Socket.IO Globales (Conexión/Desconexión/Error) ---
socket.on('connect', () => {
    console.log('Conectado al servidor Socket.IO! SID:', socket.id);
});

socket.on('disconnect', (reason) => {
    console.log('Desconectado del servidor:', reason);
    alert('Se ha perdido la conexión con el servidor de chat.');
    // Intentar deshabilitar si la función ya existe en el DOM
    if (typeof disableChatInput === "function") {
        disableChatInput();
    }
});

// Handler de errores genérico del servidor
socket.on('error', (data) => {
    console.error('Error del servidor Socket.IO:', data.message);
    // Mostrar error al usuario de forma más visible
    flashFeedback(`Error: ${data.message}`); // Usar el indicador de typing para errores
    // Podríamos querer reactivar el input si un error detuvo el proceso de unión
    // Pero cuidado, podría dejar al usuario en un estado inconsistente.
    // Quizás sea mejor resetear si el error ocurrió durante la unión.
    // if (error ocurrió durante intento de unión) { resetChatUI(); }
});

function updateTotalUnreadTitle() {
    let totalUnread = 0;
    for (const channelId in unreadCounts) {
        totalUnread += unreadCounts[channelId] || 0; // Sumar solo si existe y es > 0
    }

    if (totalUnread > 0) {
        document.title = `(${totalUnread}) ${originalTitle}`;
    } else {
        document.title = originalTitle;
    }
    // console.log("Título actualizado:", document.title, "Total unread:", totalUnread); // DEBUG opcional
}


// --- Lógica Principal (Ejecutar cuando el DOM esté listo) ---
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM cargado. Inicializando chat UI...');

    // Verificar USERNAME_GLOBAL (¡Crítico!)
    if (typeof USERNAME_GLOBAL === 'undefined' || !USERNAME_GLOBAL) {
        console.error("¡ERROR GRAVE! USERNAME_GLOBAL no está definida o está vacía. Revisa el <script> en chat_interface.html.");
        alert("Error crítico: No se pudo obtener el nombre de usuario.");
        // Podríamos deshabilitar toda la interfaz aquí
        return; // Detener inicialización
    } else {
         console.log("Username disponible en JS:", USERNAME_GLOBAL);
    }

    // --- Seleccionar Elementos del DOM ---
    const channelList = document.getElementById('channel-list-column');
    const channelListUl = document.getElementById('channel-list-ul');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const messageForm = document.getElementById('message-form');
    const messageArea = document.getElementById('message-area');
    const currentChannelNameHeader = document.getElementById('current-channel-name');
    const typingIndicator = document.getElementById('typing-indicator')?.querySelector('em');
    const leaveChannelButton = document.getElementById('leave-channel-button');
    const joinChannelModal = document.getElementById('joinChannelModal');
    const joinChannelInput = document.getElementById('join-channel-name');
    const submitJoinButton = document.getElementById('submit-join-action'); // ID corregido
    const joinChannelFeedback = document.getElementById('join-channel-feedback');
    const passwordSection = document.getElementById('join-password-section');
    const passwordInput = document.getElementById('join-channel-password');
    const bootstrapJoinModal = joinChannelModal ? new bootstrap.Modal(joinChannelModal) : null;
    const openMediaModalBtn = document.getElementById('media-popover-btn'); // Añadir


    // --- Funciones Auxiliares ---

    function enableChatInput() {
        console.log(`DEBUG: enableChatInput llamada. currentChannelId=${currentChannelId}, currentChannelIsWritable=${currentChannelIsWritable}`); // <-- AÑADIR DEBUG
        // Habilita SOLO input de texto y botón enviar SI es escribible
        const canWrite = currentChannelId !== null && currentChannelIsWritable;
        if(messageInput) messageInput.disabled = !canWrite;
        if(sendButton) sendButton.disabled = !canWrite;

        // Habilita el botón "+" SI HAY CANAL SELECCIONADO
        let isPlusButtonDisabled = (currentChannelId === null); // Calcular estado
        if(openMediaModalBtn) {
            openMediaModalBtn.disabled = isPlusButtonDisabled;
            console.log(`DEBUG: Botón '+' ${isPlusButtonDisabled ? 'DESHABILITADO' : 'HABILITADO'}`); // <-- AÑADIR DEBUG
        } else {
            console.warn("DEBUG: Botón '+' (openMediaModalBtn) no encontrado."); // <-- AÑADIR DEBUG
        }


        if (canWrite && messageInput) {
            messageInput.focus();
        }
        // Aplicar/Quitar bloqueo visual basado en canWrite
         if (messageInput) {
            if(canWrite) {
                 messageInput.classList.remove('input-locked');
                 messageInput.parentElement?.classList.remove('locked-overlay-container');
            } else if (currentChannelId !== null) { // Añadir bloqueo solo si hay canal pero no es escribible
                messageInput.classList.add('input-locked');
                messageInput.parentElement?.classList.add('locked-overlay-container');
            } else { // Quitar si no hay canal seleccionado
                 messageInput.classList.remove('input-locked');
                 messageInput.parentElement?.classList.remove('locked-overlay-container');
            }
         }
    }

    function disableChatInput() {
        // Esta función AHORA solo deshabilita TODO y limpia estados
        if(messageInput) messageInput.disabled = true;
        if(sendButton) sendButton.disabled = true;
        if(openMediaModalBtn) openMediaModalBtn.disabled = true; // Deshabilitar al inicio o al resetear
        if(typingIndicator) typingIndicator.textContent = '';
        isTyping = false;
        clearTimeout(typingTimer);
        messageInput?.classList.remove('input-locked');
        messageInput?.parentElement.classList.remove('locked-overlay-container');
    }

    function clearMessageArea() {
        if(messageArea) messageArea.innerHTML = '';
    }

    function scrollToBottom() {
        if(messageArea) messageArea.scrollTop = messageArea.scrollHeight;
    }

    function escapeHTML(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function formatMessageBody(body) {
        const escapedBody = escapeHTML(body);
        // TODO: Añadir más formato si se desea (URLs, Markdown simple, etc.)
        return escapedBody;
    }

    function createMessageElement(data) {
        const messageRow = document.createElement('div');
        messageRow.classList.add('d-flex', 'mb-2', 'message-row');
        messageRow.dataset.messageId = data.id;
        const isOwnMessage = typeof USERNAME_GLOBAL !== 'undefined' && data.username === USERNAME_GLOBAL;
        const messageContentWrapper = document.createElement('div');
        // Quitar maxWidth inicial, lo aplicaremos condicionalmente
        // messageContentWrapper.style.maxWidth = '75%';
        messageContentWrapper.classList.add('message-bubble', 'p-2', 'rounded'); // p-2 base, puede cambiar
    
        if (data.message_type === 'system') {
            messageRow.classList.add('justify-content-center');
            messageContentWrapper.classList.add('text-muted', 'fst-italic', 'text-center', 'small', 'w-100');
            messageContentWrapper.textContent = escapeHTML(data.body);
            messageContentWrapper.style.background = 'transparent'; // Sin burbuja
            messageContentWrapper.style.boxShadow = 'none';
        } else { // Mensajes de usuario
            messageRow.classList.add(isOwnMessage ? 'justify-content-end' : 'justify-content-start');
            messageContentWrapper.classList.add(isOwnMessage ? 'message-bubble-own' : 'message-bubble-other');
            if (isOwnMessage) messageContentWrapper.classList.add('text-white');
    
            const messageDate = new Date(data.timestamp);
            let messageHTML = '';
            let isMedia = false; // Flag para saber si es imagen/sticker
    
            if (!isOwnMessage) {
                messageHTML += `<small class="message-sender fw-bold d-block mb-1">${escapeHTML(data.username || 'Usuario')}</small>`;
            }
        
            // --- Lógica para Imagen/Sticker (CORREGIDA) ---
            if (data.message_type === 'image' || data.message_type === 'sticker') {
                isMedia = true;
                const mediaUrl = data.body;
                const mediaClass = data.message_type === 'sticker' ? 'message-sticker' : 'message-image';

                // Crear directamente la etiqueta IMG como contenido principal
                messageHTML += `
                    <img src="${escapeHTML(mediaUrl)}"
                        alt="${data.message_type}"
                        class="${mediaClass}"
                        style="display: block; border-radius: 8px; cursor: pointer; max-width: 100%; max-height: 250px;"
                        onclick="window.open('${escapeHTML(mediaUrl)}', '_blank')">
                `;

                // Aplicar estilos al CONTENEDOR (messageContentWrapper) para media
                messageContentWrapper.style.padding = '0'; // Sin padding en la burbuja
                messageContentWrapper.style.maxWidth = data.message_type === 'sticker' ? '150px' : '300px'; // Tamaños máximos
                messageContentWrapper.style.backgroundColor = 'transparent'; // Siempre transparente
                messageContentWrapper.style.boxShadow = 'none'; // Sin sombra de burbuja
                messageContentWrapper.classList.remove('p-2'); // Quitar padding base si lo tenía

            } else { // Mensaje de texto normal
                messageContentWrapper.style.maxWidth = '75%'; // Ancho normal para texto
                messageContentWrapper.style.padding = '8px 12px'; // Padding normal para texto (ajusta si es necesario)
                messageContentWrapper.classList.add(isOwnMessage ? 'bg-primary' : 'bg-light'); // Fondo normal para texto
                if(isOwnMessage) messageContentWrapper.classList.add('text-white');
                messageHTML += `<span class="message-body">${formatMessageBody(data.body)}</span>`;
            }
            // --- FIN NUEVA LÓGICA ---
    
            // --- Fin Lógica Media ---
    
            // Añadir timestamp (quizás fuera de la burbuja para media?)
            messageHTML += `
                <div class="timestamp ${isOwnMessage ? (isMedia ? 'text-white-50' : 'text-white-50') : 'text-muted'} ${isMedia ? 'mt-1': ''}" style="font-size: 0.7em; ${isMedia ? '' : 'margin-top: 3px;'} text-align: right;">
                    ${messageDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>`;
    
            messageContentWrapper.innerHTML = messageHTML;
        }
        messageRow.appendChild(messageContentWrapper);
        return messageRow;
    }

    function updateTypingIndicator() {
        if (!typingIndicator) return;
        if (!currentChannelId || !usersTyping[currentChannelId] || Object.keys(usersTyping[currentChannelId]).length === 0) {
            typingIndicator.textContent = ''; return;
        }
        const typingUsernames = Object.keys(usersTyping[currentChannelId]);
        const numTyping = typingUsernames.length;
        if (numTyping === 1) { typingIndicator.textContent = `${escapeHTML(typingUsernames[0])} está escribiendo...`; }
        else if (numTyping === 2) { typingIndicator.textContent = `${escapeHTML(typingUsernames[0])} y ${escapeHTML(typingUsernames[1])} están escribiendo...`; }
        else { typingIndicator.textContent = `Varios usuarios están escribiendo...`; }
    }

    function flashFeedback(message) {
        if(typingIndicator) {
            const originalText = typingIndicator.textContent;
            typingIndicator.textContent = message;
            typingIndicator.style.color = 'orange';
            setTimeout(() => { if (typingIndicator.textContent === message) { updateTypingIndicator(); typingIndicator.style.color = ''; } }, 3000);
        }
    }

    function addChannelToList(id, name) {
        const idStr = id.toString();
        if (channelListUl && !document.querySelector(`.channel-item[data-channel-id="${idStr}"]`)) {
           document.getElementById('no-channels-msg')?.remove();
           const newChannelLi = document.createElement('li');
           // ... (asignar clases y atributos como antes) ...
           newChannelLi.className = 'list-group-item list-group-item-action channel-item';
           newChannelLi.style.cursor = 'pointer';
           newChannelLi.dataset.channelId = idStr;
           newChannelLi.dataset.channelName = name;
           // Añadir data attribute para contraseña (asumimos público al añadir así)
           newChannelLi.dataset.requiresPassword = 'false'; // O obtener del backend si es posible
           newChannelLi.innerHTML = `
               ${escapeHTML(name)}
               {# Añadir icono si es protegido? Necesitaríamos esa info #}
               <span class="badge bg-danger rounded-pill float-end d-none notification-dot" id="notification-${idStr}"></span>
               {# ^^ Asegurar que el ID coincide y d-none está presente ^^ #}
           `;
           channelListUl.appendChild(newChannelLi);
           // Inicializar contador a 0 para este nuevo canal (no afecta al total)
           unreadCounts[idStr] = 0;
           return newChannelLi; // Devolver el elemento creado
       }
       return null; // Ya existía o no se pudo añadir
   }

    function resetChatUI() {
        currentChannelId = null;
        currentChannelName = null;
        currentChannelIsWritable = false;
        clearMessageArea();
        if(messageArea) messageArea.innerHTML = '<p ...>Selecciona un canal</p>';
        if(currentChannelNameHeader) currentChannelNameHeader.textContent = 'Selecciona un canal';
        disableChatInput(); // <-- Llama a la función que deshabilita todo
        leaveChannelButton?.classList.add('d-none');
        updateTypingIndicator();
        channelList?.querySelector('.active')?.classList.remove('active', 'bg-primary', 'text-white', 'rounded');
        document.title = originalTitle
         const activeChannel = channelList?.querySelector('.active');
         activeChannel?.classList.remove('active', 'bg-primary', 'text-white', 'rounded');
         // Mostrar mensaje "No estás en ningún canal" si la lista queda vacía
         if (channelListUl && !channelListUl.querySelector('.channel-item') && !document.getElementById('no-channels-msg')) {
             const noChannelsLi = document.createElement('li');
             noChannelsLi.className = 'list-group-item';
             noChannelsLi.id = 'no-channels-msg';
             noChannelsLi.textContent = 'No estás en ningún canal aún.';
             channelListUl.appendChild(noChannelsLi);
         }
    }

        // --- Función para actualizar la UI al cambiar de canal ---
        function setActiveChannelUI(channelId, channelName, isProtected) {
            const channelIdStr = channelId.toString(); // Asegurar string

            // Resetear contador y badge para el canal que AHORA está activo
            if (unreadCounts[channelIdStr] > 0) {
                console.log(`Reseteando contador para canal activo ${channelIdStr}`); // DEBUG
                unreadCounts[channelIdStr] = 0;
                updateTotalUnreadTitle(); // Recalcular total para la pestaña
            }
            const notificationDot = channelList?.querySelector(`#notification-${channelIdStr}`);
            if (notificationDot) {
                notificationDot.textContent = '';
                notificationDot.classList.add('d-none');
            }

            // --- Lógica existente para actualizar UI ---
            currentChannelId = channelIdStr;
            currentChannelName = channelName;
            currentChannelIsWritable = false;

            channelList?.querySelector('.active')?.classList.remove('active', 'bg-primary', 'text-white', 'rounded');
            const channelItem = channelList?.querySelector(`.channel-item[data-channel-id="${channelId}"]`);
            if(channelItem) {
                channelItem.classList.add('active', 'bg-primary', 'text-white', 'rounded');
            }

            if(currentChannelNameHeader) currentChannelNameHeader.textContent = channelName;
            if(messageArea) messageArea.innerHTML = `<p class="text-muted text-center" id="chat-placeholder">Cargando mensajes...</p>`;
            disableChatInput();
            leaveChannelButton?.classList.remove('d-none');
            if(typingIndicator) typingIndicator.textContent = '';
            usersTyping[currentChannelId] = usersTyping[currentChannelId] || {};

            console.log(`UI actualizada para canal activo: ${channelName} (ID: ${channelId})`);
            socket.emit('request_history', { channel_id: currentChannelId });
            // El backend enviará 'channel_status'
        }

    // --- Registrar Manejadores Socket.IO ---

    socket.on('new_message', (data) => {
        const msgChannelId = data.channel_id?.toString(); // Asegurar string

        // Si el mensaje es para el canal ACTIVO, simplemente añadirlo
        if (msgChannelId === currentChannelId) {
            if (messageArea) {
                document.getElementById('chat-placeholder')?.remove();
                const messageElement = createMessageElement(data);
                messageArea.appendChild(messageElement);
                scrollToBottom();
            }
        }
        // Si el mensaje es para un canal INACTIVO
        else if (msgChannelId) {
            console.log(`Mensaje recibido para canal inactivo: ${msgChannelId}`); // DEBUG
            // Incrementar contador
            unreadCounts[msgChannelId] = (unreadCounts[msgChannelId] || 0) + 1;
            // Actualizar badge
            const notificationDot = document.getElementById(`notification-${msgChannelId}`);
            if (notificationDot) {
                notificationDot.textContent = unreadCounts[msgChannelId];
                notificationDot.classList.remove('d-none'); // Mostrarlo
                console.log(`Badge actualizado para ${msgChannelId}: ${unreadCounts[msgChannelId]}`); // DEBUG
            } else {
                console.warn(`Badge #notification-${msgChannelId} no encontrado.`); // DEBUG
            }
            // Actualizar título de la pestaña
            updateTotalUnreadTitle();
        } else {
             console.warn("Mensaje recibido sin channel_id:", data);
        }
    });

    socket.on('channel_history', (data) => {
        // Solo mostrar historial si es para el canal activo
         if (data.channel_id?.toString() === currentChannelId) {
            console.log(`Historial recibido para canal activo ${currentChannelId}: ${data.messages?.length} mensajes`);
            if(messageArea){
                clearMessageArea(); // Limpiar "Cargando..."
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(messageData => {
                        const messageElement = createMessageElement(messageData);
                        messageArea.appendChild(messageElement);
                    });
                    scrollToBottom();
                } else {
                    messageArea.innerHTML = '<p class="text-muted text-center" id="chat-placeholder">No hay mensajes en este canal. ¡Sé el primero!</p>';
                }
            }
         } else {
              console.log(`Historial recibido para canal INACTIVO (${data.channel_id}), ignorando.`);
         }
    });

    socket.on('user_typing', (data) => {
        if (data.channel_id?.toString() === currentChannelId && data.username !== USERNAME_GLOBAL) {
            usersTyping[currentChannelId] = usersTyping[currentChannelId] || {};
            usersTyping[currentChannelId][data.username] = true;
            updateTypingIndicator();
        }
    });

    socket.on('user_stopped_typing', (data) => {
        if (data.channel_id?.toString() === currentChannelId) {
            if (usersTyping[currentChannelId]?.[data.username]) {
                delete usersTyping[currentChannelId][data.username];
                updateTypingIndicator();
            }
        }
    });

    socket.on('channel_status', (data) => {
        // Solo actualizar si el status es para el canal actualmente activo en el cliente
        if (data.channel_id?.toString() === currentChannelId) {
            console.log(`Estado recibido para canal activo ${currentChannelId}:`, data);
            currentChannelIsWritable = data.is_writable;
            // enableChatInput YA se llama desde setActiveChannelUI o el listener de click público.
            // Aquí solo ajustamos basado en el estado recibido.
            enableChatInput(); // Asegura que el input refleje el estado de escritura correcto
        } else {
             console.log(`Estado recibido para canal INACTIVO (${data.channel_id}), ignorando para UI principal.`);
        }
    });

    socket.on('channel_status_update', (data) => {
        if (data.channel_id?.toString() === currentChannelId) {
             console.log(`Actualización estado canal ${currentChannelId}:`, data);
            currentChannelIsWritable = data.is_writable;
            enableChatInput();
            flashFeedback(currentChannelIsWritable ? 'La escritura ha sido habilitada.' : 'La escritura ha sido deshabilitada.');
        }
    });

    socket.on('join_channel_feedback', (data) => {
        console.log("Feedback modal unión:", data);
        if (joinChannelFeedback && submitJoinButton && bootstrapJoinModal) {
             submitJoinButton.disabled = false; // Siempre re-habilitar botón al recibir feedback
             let feedbackClass = 'text-info small mt-2'; // Default a info
             let shouldCloseModal = false;
             let closeDelay = 0;

            if (data.error) { feedbackClass = 'text-danger small mt-2'; }
            else if (data.success) { feedbackClass = 'text-success small mt-2'; shouldCloseModal = true; closeDelay = 2500; }
            else if (data.info) { feedbackClass = 'text-info small mt-2'; shouldCloseModal = true; closeDelay = data.already_member ? 0 : 3000; } // Cerrar rápido si ya es miembro

            joinChannelFeedback.textContent = data.error || data.info || data.success || 'Respuesta desconocida.';
            joinChannelFeedback.className = feedbackClass;

            // Resetear estado si no fue error de contraseña incorrecta
             if(data.error !== 'Contraseña incorrecta.') {
                 foundChannelInfo = null;
                 submitJoinButton.textContent = 'Buscar Canal';
                 passwordSection?.classList.add('d-none');
             } else {
                 submitJoinButton.textContent = 'Introducir Contraseña y Unirse/Solicitar';
                 passwordInput?.focus();
                 passwordInput?.select();
             }

             // Cerrar modal si aplica
             if (shouldCloseModal && bootstrapJoinModal) {
                 setTimeout(() => bootstrapJoinModal.hide(), closeDelay);
             }
              // Si ya era miembro, emitir evento para añadir a lista por si acaso
             if(data.already_member && data.channel_id) {
                addChannelToList(data.channel_id, data.channel_name);
            }
        }
    });

    socket.on('channel_info_found', (data) => {
        console.log("Info canal encontrada:", data);
        foundChannelInfo = data; // Guardar estado

        if (joinChannelFeedback && submitJoinButton && passwordSection && bootstrapJoinModal) {
            submitJoinButton.disabled = false;
            let feedbackText = `Canal "${data.channel_name}" encontrado. `;
            let buttonText = '';

            if (data.requires_password) {
                feedbackText += "Requiere contraseña.";
                passwordSection.classList.remove('d-none');
                passwordInput.value = '';
                passwordInput.focus();
                buttonText = 'Introducir Contraseña y ';
            } else {
                feedbackText += "No requiere contraseña.";
                passwordSection.classList.add('d-none');
            }
            buttonText += data.requires_approval ? 'Solicitar Acceso' : 'Unirse';

            if (data.requires_approval) { feedbackText += " Requiere aprobación."; }
            else { feedbackText += " Acceso inmediato."; }

            joinChannelFeedback.textContent = feedbackText;
            joinChannelFeedback.className = 'text-info small mt-2';
            submitJoinButton.textContent = buttonText;
        }
    });

    socket.on('new_channel_joined', (data) => {
        console.log("Evento 'new_channel_joined' recibido:", data);
        const joinedChannelId = data.id?.toString();
        const joinedChannelName = data.name;

        // Si este evento llega DESPUÉS de intentar unirse con contraseña,
        // AHORA es el momento de actualizar la UI principal.
        // Comprobamos si el ID coincide con el que se estaba intentando unir
        // (Podríamos guardar el ID que se intenta unir en una variable temporal si es necesario,
        // pero generalmente, este evento solo llegará para el canal correcto en este contexto).

        // No necesitamos comprobar si ya existe en la lista, addChannelToList lo hace.
        addChannelToList(joinedChannelId, joinedChannelName);

        // --- ACTUALIZAR UI PRINCIPAL ---
        // Llamamos a la función que centraliza la actualización de la UI
        // Necesitamos saber si era protegido, podemos deducirlo buscando el item
        const channelItem = channelList?.querySelector(`.channel-item[data-channel-id="${joinedChannelId}"]`);
        const isProtected = channelItem?.dataset.requiresPassword === 'true';
        setActiveChannelUI(joinedChannelId, joinedChannelName, isProtected);

        // Cerrar modal de unión si estaba abierto (puede que ya esté cerrado)
        bootstrapJoinModal?.hide();
    });

    socket.on('request_approved', (data) => {
         console.log("Solicitud aprobada:", data);
         alert(data.message || `Solicitud para "${data.channel_name}" aprobada.`);
         const addedLi = addChannelToList(data.channel_id, data.channel_name);
         // Opcional: Hacer clic para entrar automáticamente
         // if (addedLi) addedLi.click();
    });

    socket.on('request_rejected', (data) => {
         console.log("Solicitud rechazada:", data);
         alert(data.message || `Solicitud para "${data.channel_name}" rechazada.`);
    });

    // --- MODIFICAR handlers de salida/kick ---
    socket.on('left_channel_successfully', (data) => {
        const leftChannelId = data.channel_id?.toString();
        if (leftChannelId) {
            console.log(`Salida confirmada canal ${leftChannelId}`);
            document.querySelector(`.channel-item[data-channel-id="${leftChannelId}"]`)?.remove();
            // Eliminar contador y actualizar título
            if (unreadCounts[leftChannelId]) {
                delete unreadCounts[leftChannelId];
                updateTotalUnreadTitle();
            }
            if (leftChannelId === currentChannelId) {
                resetChatUI(); // Usar función para resetear
            }
        }
     });

    socket.on('kicked_from_channel', (data) => {
        const kickedChannelId = data.channel_id?.toString();
        if (kickedChannelId) {
             alert(data.message || `Has sido kickeado del canal ID ${kickedChannelId}`);
             console.log(`Kickeado canal ${kickedChannelId}`);
             document.querySelector(`.channel-item[data-channel-id="${kickedChannelId}"]`)?.remove();
             // Eliminar contador y actualizar título
             if (unreadCounts[kickedChannelId]) {
                 delete unreadCounts[kickedChannelId];
                 updateTotalUnreadTitle();
             }
             if (kickedChannelId === currentChannelId) {
                 resetChatUI(); // Usar función para resetear
             }
         }
     });


    // --- Registrar Listeners del DOM ---

    // --- Listener Click en Lista de Canales (Modificado) ---
    if (channelList) {
        channelList.addEventListener('click', (event) => {
            const channelItem = event.target.closest('.channel-item');
            if (!channelItem || !channelItem.dataset.channelId) return;

            const newChannelId = channelItem.dataset.channelId;
            const newChannelName = channelItem.dataset.channelName;
            const requiresPassword = channelItem.dataset.requiresPassword === 'true';

            if (newChannelId === currentChannelId) return; // No hacer nada si ya está activo

            console.log(`Intentando cambiar a canal: ${newChannelName} (ID: ${newChannelId}), Protegido: ${requiresPassword}`);

            // Salir de la sala del canal anterior en el backend
            if (currentChannelId !== null) {
                socket.emit('leave_channel', { channel_id: currentChannelId });
                if(usersTyping[currentChannelId]) delete usersTyping[currentChannelId]; // Limpiar typing local
            }

            // Mostrar feedback inmediato y deshabilitar
            if(currentChannelNameHeader) currentChannelNameHeader.textContent = newChannelName;
            if(messageArea) messageArea.innerHTML = `<p class="text-muted text-center" id="chat-placeholder">${requiresPassword ? 'Verificando contraseña...' : 'Cargando...'}</p>`;
            disableChatInput();
            leaveChannelButton?.classList.add('d-none'); // Ocultar botón salir temporalmente

            // --- Lógica separada para público y protegido ---
            if (requiresPassword) {
                 // 1. PEDIR CONTRASEÑA
                const enteredPassword = prompt(`El canal "${newChannelName}" requiere contraseña:`);

                if (enteredPassword === null) { // Usuario canceló el prompt
                    console.log("Prompt de contraseña cancelado.");
                     // Restaurar UI a "Selecciona canal" si no había canal previo
                     if (currentChannelId === null) {
                         resetChatUI();
                     } else {
                          // Volver a seleccionar visualmente el canal anterior si existía
                         const previousChannelItem = channelList.querySelector(`.channel-item[data-channel-id="${currentChannelId}"]`);
                         if (previousChannelItem) {
                              // No necesitamos re-emitir 'join', solo restaurar estado visual
                              previousChannelItem.classList.add('active', 'bg-primary', 'text-white', 'rounded');
                              const previousChannelName = previousChannelItem.dataset.channelName;
                              if(currentChannelNameHeader) currentChannelNameHeader.textContent = previousChannelName;
                              // Podríamos re-solicitar status/historial si fuera necesario, pero usualmente no lo es
                              socket.emit('request_history', { channel_id: currentChannelId }); // Pedir historial por si acaso
                              enableChatInput(); // Re-habilitar basado en el estado anterior
                              leaveChannelButton?.classList.remove('d-none');
                         } else {
                              resetChatUI(); // Si no encontramos el item anterior, resetear
                         }
                     }
                    return; // Detener proceso
                }

                // 2. EMITIR evento con contraseña (incluso si está vacía)
                 console.log(`Enviando intento de unión con contraseña a canal ${newChannelId}`);
                 socket.emit('join_channel_with_password', { channel_id: newChannelId, password: enteredPassword });
                 // NO actualizamos currentChannelId/Name aquí. Esperamos respuesta del servidor.

            } else {
                 // --- Canal Público ---
                 // 1. EMITIR evento de unión simple
                 console.log(`Enviando intento de unión (público) a canal ${newChannelId}`);
                 socket.emit('join_channel', { channel_id: newChannelId });

                 // 2. ACTUALIZAR UI INMEDIATAMENTE (Optimista)
                 // La función setActiveChannelUI ahora hace esto
                 setActiveChannelUI(newChannelId, newChannelName, false);
            }
        });
    } else { console.error("#channel-list-column no encontrado"); }

    if (messageForm) {
        messageForm.addEventListener('submit', (event) => {
            event.preventDefault();
            if (!currentChannelId || !messageInput || !currentChannelIsWritable) return;
            const messageBody = messageInput.value.trim();
            if (messageBody === '') return;
            socket.emit('send_message', { channel_id: currentChannelId, body: messageBody });
            messageInput.value = ''; messageInput.focus();
            if (isTyping) { clearTimeout(typingTimer); socket.emit('typing_stopped', { channel_id: currentChannelId }); isTyping = false; updateTypingIndicator(); }
        });
     } else { console.error("#message-form no encontrado"); }

    if (messageInput) {
        messageInput.addEventListener('input', () => {
            if (!currentChannelId || !currentChannelIsWritable) return;
            if (!isTyping) { socket.emit('typing_started', { channel_id: currentChannelId }); isTyping = true; }
            clearTimeout(typingTimer);
            typingTimer = setTimeout(() => { if(isTyping) { socket.emit('typing_stopped', { channel_id: currentChannelId }); isTyping = false; } }, typingTimeout);
        });
        messageInput.addEventListener('blur', () => { if (isTyping && currentChannelId) { clearTimeout(typingTimer); socket.emit('typing_stopped', { channel_id: currentChannelId }); isTyping = false; } });
    } else { console.error("#message-input no encontrado"); }

    // Listener para Modal "Unirse"
    if (submitJoinButton && joinChannelInput && joinChannelFeedback && bootstrapJoinModal && passwordSection && passwordInput) {
         submitJoinButton.addEventListener('click', () => {
            joinChannelFeedback.textContent = '';
            // Fase 1: Buscar
            if (!foundChannelInfo) {
                const channelName = joinChannelInput.value.trim();
                if (channelName.length < 3) { joinChannelFeedback.textContent = 'Nombre muy corto.'; joinChannelFeedback.className = 'text-danger small mt-2'; return; }
                joinChannelFeedback.textContent = 'Buscando...'; joinChannelFeedback.className = 'text-info small mt-2'; submitJoinButton.disabled = true;
                passwordSection.classList.add('d-none'); passwordInput.value = '';
                socket.emit('find_channel_info', { channel_name: channelName });
            }
            // Fase 2: Unirse/Solicitar
            else {
                const password = passwordInput.value;
                if (foundChannelInfo.requires_password && !password) { joinChannelFeedback.textContent = 'Contraseña requerida.'; joinChannelFeedback.className = 'text-danger small mt-2'; return; }
                joinChannelFeedback.textContent = 'Procesando...'; joinChannelFeedback.className = 'text-info small mt-2'; submitJoinButton.disabled = true;
                socket.emit('attempt_join', { channel_id: foundChannelInfo.channel_id, channel_name: foundChannelInfo.channel_name, password: password });
            }
        });
        joinChannelModal.addEventListener('hidden.bs.modal', () => {
             joinChannelInput.value = ''; passwordInput.value = '';
             passwordSection.classList.add('d-none'); joinChannelFeedback.textContent = '';
             submitJoinButton.textContent = 'Buscar Canal'; submitJoinButton.disabled = false;
             foundChannelInfo = null; // Resetear
        });
    } else { console.error("Error: Elementos del modal #joinChannelModal incompletos"); }

    const mediaPopoverBtn = document.getElementById('media-popover-btn');
    const directImageUploadInput = document.getElementById('direct-image-upload-input');
    const stickerUploadInput = document.getElementById('sticker-upload-input');
    let mediaPopoverInstance = null; // Guardar instancia del popover

        // --- INICIALIZAR POPOVER INICIAL ---
        function initializePopover(buttonElement) {
            // Destruir instancia anterior si existe
            if (mediaPopoverInstance) {
                mediaPopoverInstance.dispose();
                mediaPopoverInstance = null;
                console.log("DEBUG: Instancia Popover anterior destruida.");
            }
            // Crear nueva instancia
            mediaPopoverInstance = new bootstrap.Popover(buttonElement, {
                content: function() {
                    const contentId = buttonElement.getAttribute('data-bs-content-id');
                    const template = document.getElementById(contentId);
                    return template ? template.innerHTML : 'Error al cargar contenido.';
                },
                html: true, // Necesario para nuestro contenido
                sanitize: false, // Permitimos nuestro HTML (¡cuidado!)
                placement: 'top',
                customClass: 'media-popover',
                trigger: 'manual' // Controlaremos manualmente mostrar/ocultar
            });
            console.log("DEBUG: Nueva instancia Popover inicializada.");
        }

        if (mediaPopoverBtn) {
            // Inicializar al cargar la página
            initializePopover(mediaPopoverBtn);

            
            // Listener para ABRIR/CERRAR el Popover manualmente
            mediaPopoverBtn.addEventListener('click', (event) => {
                event.stopPropagation(); // Evitar que el clic se propague al body
                if (mediaPopoverInstance) {
                    // Si ya está visible, lo ocultamos y reinicializamos
                    const visiblePopover = document.getElementById(mediaPopoverBtn.getAttribute('aria-describedby'));
                    if(visiblePopover) {
                        mediaPopoverInstance.hide();
                        mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content'); // Resetear contenido
                        initializePopover(mediaPopoverBtn); // Reinicializar
                        console.log("DEBUG: Popover ocultado y reinicializado.");
                    } else {
                        // Si no está visible, lo mostramos (asegurando contenido inicial)
                        mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content');
                        initializePopover(mediaPopoverBtn); // Asegurar que es la instancia correcta
                        mediaPopoverInstance.show();
                        console.log("DEBUG: Popover mostrado con opciones iniciales.");
                    }
                } else {
                    // Si no hay instancia (raro), intentar inicializar y mostrar
                    mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content');
                    initializePopover(mediaPopoverBtn);
                    mediaPopoverInstance.show();
                    console.log("DEBUG: Popover inicializado y mostrado (caso raro).");
                }
            });

            // Listener en el BODY para clics DENTRO del popover o FUERA para cerrar
            document.body.addEventListener('click', function(event) {
                if (!mediaPopoverInstance) return;
                const visiblePopover = document.getElementById(mediaPopoverBtn.getAttribute('aria-describedby'));

                // Cerrar si se hace clic fuera
                if (visiblePopover && !visiblePopover.contains(event.target) && event.target !== mediaPopoverBtn && !mediaPopoverBtn.contains(event.target)) {
                    mediaPopoverInstance.hide();
                    // Resetear al contenido inicial para la próxima vez que se abra
                    mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content');
                    initializePopover(mediaPopoverBtn); // Reinicializar al cerrar
                    console.log("DEBUG: Clic fuera, Popover ocultado y reinicializado.");
                    return;
                }

                // Si el clic fue dentro del popover visible
                if (visiblePopover && visiblePopover.contains(event.target)) {
                    const popoverBody = visiblePopover.querySelector('.popover-body');
                    if (!popoverBody || !popoverBody.contains(event.target)) return;

                    // Clic en "Enviar Imagen"
                    if (event.target.closest('#popover-send-image-btn')) {
                        console.log("Clic en Enviar Imagen");
                        directImageUploadInput?.click();
                        mediaPopoverInstance.hide();
                        mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content'); // Resetear
                        initializePopover(mediaPopoverBtn); // Reinicializar
                    }
                    // Clic en "Stickers"
                    else if (event.target.closest('#popover-open-stickers-btn')) {
                        console.log("Clic en Abrir Stickers");
                        mediaPopoverBtn.setAttribute('data-bs-content-id', 'sticker-selector-content'); // Cambiar ID de contenido
                        initializePopover(mediaPopoverBtn); // REINICIALIZAR con el nuevo content ID
                        mediaPopoverInstance.show(); // Mostrar el nuevo popover
                        console.log("DEBUG: Popover REINICIALIZADO para mostrar stickers.");
                        // Llamar a cargar stickers DESPUÉS de que se muestre (Bootstrap dispara 'shown.bs.popover')
                        // Lo haremos en un listener aparte (ver abajo)
                    }
                    
                    // --- Clic en un Sticker ---
                    else if (event.target.closest('.popover-sticker-item')) {
                        const stickerItem = event.target.closest('.popover-sticker-item');
                        const stickerUrl = stickerItem.dataset.stickerUrl;
                        if (stickerUrl && currentChannelId) {
                            console.log(`Enviando sticker (como imagen): ${stickerUrl}`);
                            // --- CAMBIO AQUÍ ---
                            socket.emit('send_message', {
                                channel_id: currentChannelId,
                                body: stickerUrl,        // La URL del sticker
                                message_type: 'image'    // <-- Enviar como tipo 'image'
                            });
                            // --- FIN CAMBIO ---
                            mediaPopoverInstance?.hide();
                        }
                    }

                    // Clic en "Subir" sticker
                    else if (event.target.closest('#popover-upload-sticker-btn')) {
                        console.log("Clic en Subir Sticker para Aprobación");
                        stickerUploadInput?.click();
                        // No cerramos el popover aquí necesariamente
                    }
                }
            }); // Fin listener body click

            // Listener para evento 'shown.bs.popover' - Se dispara DESPUÉS de que el popover (nuevo o actualizado) se muestra
            mediaPopoverBtn.addEventListener('shown.bs.popover', () => {
                const currentContentId = mediaPopoverBtn.getAttribute('data-bs-content-id');
                console.log(`DEBUG: Popover mostrado. Content ID: ${currentContentId}`);
                // Si el contenido es el de stickers, llamar a cargar AHORA
                if (currentContentId === 'sticker-selector-content') {
                    console.log("DEBUG: Popover de stickers mostrado, llamando a loadStickersIntoPopover.");
                    loadStickersIntoPopover();
                }
            });

            // ... (Listeners para inputs de subida de archivo - sin cambios) ...
            if(directImageUploadInput) { /* ... listener 'change' para uploadMediaFile(file, false) ... */ }
            if(stickerUploadInput) { /* ... listener 'change' para uploadMediaFile(file, true) ... */ }

        } // Fin if (mediaPopoverBtn)


    // --- Función para Cargar Stickers en el Popover ---
    function loadStickersIntoPopover() {
        // IMPORTANTE: Buscar el grid DENTRO del popover visible en este momento
        const visiblePopover = document.getElementById(mediaPopoverBtn.getAttribute('aria-describedby'));
        const stickerGrid = visiblePopover?.querySelector('#popover-sticker-grid'); // Buscar dentro del visible
        if (!stickerGrid) {
            console.error("!!! DEBUG loadStickers: #popover-sticker-grid NO encontrado en popover visible.");
            return;
        }
        console.log("!!! DEBUG loadStickers: Grid encontrado, poniendo 'Cargando...'");
        stickerGrid.innerHTML = '<span class="text-muted small">Cargando stickers...</span>';
        // ... (Resto de la función fetch sin cambios) ...
        fetch('/get-approved-stickers')
            .then(response => { /* ... */ return response.json(); })
            .then(stickers => {
                console.log("!!! DEBUG loadStickers: Fetch OK, mostrando stickers.");
                stickerGrid.innerHTML = '';
                if (stickers && stickers.length > 0) {
                    stickers.forEach(sticker => {
                        const stickerDiv = document.createElement('div');
                        stickerDiv.className = 'popover-sticker-item';
                        stickerDiv.dataset.stickerUrl = sticker.url;
                        stickerDiv.innerHTML = `<img src="${escapeHTML(sticker.url)}" alt="Sticker ${sticker.id}" title="Sticker ${sticker.id}">`;
                        stickerGrid.appendChild(stickerDiv);
                    });
                } else {
                    stickerGrid.innerHTML = '<span class="text-muted small">No hay stickers.</span>';
                }
            })
            .catch(error => { /* ... */ });
    }

    // --- Función para Subir Archivo (AJAX) ---
    // --- Función para Subir Archivo (Revisada para Popover) ---
    function uploadMediaFile(file, isStickerForApproval) {
        // ... (validaciones iniciales: file, channelId if needed, size) ...
         if (!file) return;
         if (!currentChannelId && !isStickerForApproval) {
             alert("Selecciona un canal antes de enviar una imagen.");
             resetUploadInput(isStickerForApproval); return;
         }
         const maxSize = 5 * 1024 * 1024; // 5MB
         if (file.size > maxSize) {
              alert(`El archivo es demasiado grande (Máx: ${maxSize / 1024 / 1024} MB).`);
              resetUploadInput(isStickerForApproval); return;
         }

        console.log(`[uploadMediaFile] Iniciando subida. Sticker? ${isStickerForApproval}, File: ${file.name}`); // DEBUG

        const formData = new FormData();
        formData.append('media_file', file);
        formData.append('is_sticker_submission', isStickerForApproval);
        if (!isStickerForApproval) {
            formData.append('channel_id', currentChannelId);
        }

        // --- IMPORTANTE: Buscar elementos UI DENTRO del Popover si es sticker ---
        let feedbackDiv, progressBarContainer, progressBarInner, uploadButton;
        const visiblePopover = document.getElementById(mediaPopoverBtn?.getAttribute('aria-describedby'));

        if (isStickerForApproval) {
            if (!visiblePopover) {
                console.error("Error: Popover de stickers no encontrado para mostrar feedback.");
                // Podríamos intentar mostrar un alert genérico
                alert("Iniciando subida de sticker...");
            }
            feedbackDiv = visiblePopover?.querySelector('#popover-upload-feedback');
            progressBarContainer = visiblePopover?.querySelector('#popover-upload-progress');
            progressBarInner = progressBarContainer?.querySelector('.progress-bar');
            uploadButton = visiblePopover?.querySelector('#popover-upload-sticker-btn');
            console.log("[uploadMediaFile] Buscando elementos UI dentro del popover:", { feedbackDiv, progressBarContainer, uploadButton }); // DEBUG
        } else {
            // Para imagen directa, usar elementos fuera del popover (si los tienes)
            feedbackDiv = document.getElementById('upload-feedback'); // ID genérico fuera
            progressBarContainer = document.getElementById('upload-progress-bar'); // ID genérico fuera
            progressBarInner = progressBarContainer?.querySelector('.progress-bar');
            uploadButton = null; // No aplica botón específico aquí
        }

        // --- Resetear y preparar UI de subida ---
        if (feedbackDiv) { feedbackDiv.textContent = 'Subiendo...'; feedbackDiv.className = 'small text-info mt-1'; feedbackDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } // Scroll para verlo
        if (progressBarContainer) progressBarContainer.classList.remove('d-none');
        if (progressBarInner) progressBarInner.style.width = '0%';
        if (uploadButton) uploadButton.disabled = true; // Deshabilitar botón subir sticker

        // Ocultar popover inmediatamente si es imagen directa
        if (mediaPopoverInstance && !isStickerForApproval) {
            mediaPopoverInstance.hide();
        }

        // --- Fetch API ---
        fetch('/upload-media', {
            method: 'POST',
            body: formData,
        })
        .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data }))) // Siempre parsear JSON
        .then(({ ok, status, data }) => {
            if (!ok) {
                 // Lanzar error con mensaje del servidor si existe
                 throw new Error(data.error || `Error ${status} del servidor.`);
            }
            // --- Éxito ---
            console.log('[uploadMediaFile] Respuesta OK:', data);
            if (feedbackDiv) {
                feedbackDiv.textContent = data.message || (isStickerForApproval ? 'Sticker enviado.' : 'Imagen enviada.');
                feedbackDiv.className = 'small text-success mt-1';
            }
            // Ocultar popover de stickers después de un delay
            if (mediaPopoverInstance && isStickerForApproval) {
                setTimeout(() => {
                    // Solo ocultar si aún está visible (el usuario podría haberlo cerrado)
                    const currentPopover = document.getElementById(mediaPopoverBtn?.getAttribute('aria-describedby'));
                    if (currentPopover) {
                        mediaPopoverInstance?.hide();
                        // Resetear estado del botón por si acaso (aunque finally lo hace)
                         if (uploadButton) uploadButton.disabled = false;
                         // Podríamos querer reiniciar el popover a opciones iniciales
                         // mediaPopoverBtn?.setAttribute('data-bs-content-id', 'media-options-content');
                         // initializePopover(mediaPopoverBtn); // Cuidado, esto puede ser abrupto
                    }
                }, 2000); // 2 segundos
            }
        })
        .catch(error => {
            // --- Error ---
            console.error('[uploadMediaFile] Error en subida:', error);
            if (feedbackDiv) {
                feedbackDiv.textContent = `Error: ${error.message}`;
                feedbackDiv.className = 'small text-danger mt-1';
            }
            // Mantener popover abierto en error, reactivar botón
            if (uploadButton) uploadButton.disabled = false;
        })
        .finally(() => {
            // --- Siempre al finalizar ---
            // Ocultar barra de progreso
            if (progressBarContainer) progressBarContainer.classList.add('d-none');
            if (progressBarInner) progressBarInner.style.width = '0%';
            // Asegurar reactivación del botón (por si acaso)
            if (uploadButton) uploadButton.disabled = false;
            // Resetear input de archivo
            resetUploadInput(isStickerForApproval);
            console.log("[uploadMediaFile] Subida finalizada (finally)."); // DEBUG
        });
    }

    // --- Función auxiliar para resetear input file ---
    function resetUploadInput(isSticker) {
        const inputId = isSticker ? 'sticker-upload-input' : 'direct-image-upload-input';
        const inputElement = document.getElementById(inputId);
        if (inputElement) {
            inputElement.value = ''; // Resetea la selección
            console.log(`[resetUploadInput] Input ${inputId} reseteado.`); //DEBUG
        }
    }

    // --- Lógica del Popover de Media (Revisada) ---
    if (mediaPopoverBtn) {
        // Inicializar Popover (Función initializePopover como antes)
        initializePopover(mediaPopoverBtn); // Asegúrate que esta función exista y funcione

        // Listener para ABRIR/CERRAR el Popover
        mediaPopoverBtn.addEventListener('click', (event) => {
             // ... (lógica de abrir/cerrar y reinicializar como antes) ...
        });

        // Listener en el BODY para clics DENTRO o FUERA
        document.body.addEventListener('click', function(event) {
            if (!mediaPopoverInstance) return;
            const visiblePopover = document.getElementById(mediaPopoverBtn.getAttribute('aria-describedby'));

            // Cerrar si clic fuera
            if (visiblePopover && !visiblePopover.contains(event.target) && event.target !== mediaPopoverBtn && !mediaPopoverBtn.contains(event.target)) {
                 // ... (lógica de cerrar y reinicializar como antes) ...
                return;
            }

            // Si clic DENTRO del popover visible
            if (visiblePopover && visiblePopover.contains(event.target)) {
                const popoverBody = visiblePopover.querySelector('.popover-body');
                if (!popoverBody || !popoverBody.contains(event.target)) return;

                // --- Click en "Enviar Imagen" (Popover Inicial) ---
                if (event.target.closest('#popover-send-image-btn')) {
                    console.log("Clic en Enviar Imagen");
                    directImageUploadInput?.click(); // Activa input oculto de imagen
                    mediaPopoverInstance.hide(); // Ocultar popover
                    // Resetear popover a estado inicial (opcional pero bueno)
                    // mediaPopoverBtn.setAttribute('data-bs-content-id', 'media-options-content');
                    // initializePopover(mediaPopoverBtn);
                }
                // --- Click en "Stickers" (Popover Inicial) ---
                else if (event.target.closest('#popover-open-stickers-btn')) {
                    // ... (lógica para cambiar contenido y mostrar popover de stickers como antes) ...
                }
                // --- Click en un Sticker para ENVIAR ---
                else if (event.target.closest('.popover-sticker-item')) {
                     // ... (lógica para enviar sticker como antes, usando message_type: 'image') ...
                }
                // --- Click en "Subir Sticker" (Popover de Stickers) ---
                else if (event.target.closest('#popover-upload-sticker-btn')) {
                    console.log("Clic en Subir Sticker (activa input oculto)");
                    // Limpiar feedback anterior antes de abrir el diálogo
                    const feedbackDiv = visiblePopover?.querySelector('#popover-upload-feedback');
                    if(feedbackDiv) feedbackDiv.textContent = '';
                    stickerUploadInput?.click(); // <<-- IMPORTANTE: Activa el input oculto correcto
                    // NO cerramos el popover aquí, esperamos la selección de archivo
                }
            }
        }); // Fin listener body click

        // Listener para evento 'shown.bs.popover' (como antes)
        mediaPopoverBtn.addEventListener('shown.bs.popover', () => {
            // ... (lógica para cargar stickers si es el popover correcto) ...
        });

        // --- Listeners para los inputs de archivo (¡Verificar!) ---
        if (directImageUploadInput) {
            console.log("Element #direct-image-upload-input ENCONTRADO.");
            directImageUploadInput.addEventListener('change', (event) => {
                 console.log("[EVENT] 'change' en #direct-image-upload-input detectado."); // Log event firing
                 const file = event.target.files ? event.target.files[0] : null;
                 console.log("[Listener Change] Imagen directa seleccionada:", file?.name);
                 if (file) {
                     uploadMediaFile(file, false);
                 } else {
                     console.log("[Listener Change] No se seleccionó archivo válido (imagen directa).");
                 }
            });
            console.log("Listener 'change' AÑADIDO a #direct-image-upload-input.");
        } else {
            console.error("CRITICAL: Element #direct-image-upload-input NO encontrado en el DOM.");
        }
    
        if (stickerUploadInput) {
            console.log("Element #sticker-upload-input ENCONTRADO."); // <-- LOG 1
            stickerUploadInput.addEventListener('change', (event) => {
                console.log("[EVENT] 'change' en #sticker-upload-input detectado."); // <-- LOG 3: ¿Se dispara?
                const file = event.target.files ? event.target.files[0] : null;
                console.log("[Listener Change] Sticker para aprobación seleccionado:", file?.name); // <-- LOG 4: ¿Se obtiene el archivo?
                if (file) {
                     uploadMediaFile(file, true);
                } else {
                     console.log("[Listener Change] No se seleccionó archivo válido (sticker).");
                }
             });
             console.log("Listener 'change' AÑADIDO a #sticker-upload-input."); // <-- LOG 2: ¿Se añade?
        } else {
            console.error("CRITICAL: Element #sticker-upload-input NO encontrado en el DOM.");
        }

    } // Fin if (mediaPopoverBtn)

}); // <-- FIN del DOMContentLoaded