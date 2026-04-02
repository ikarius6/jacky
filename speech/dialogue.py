import random
from typing import Optional

DIALOGUE_POOLS = {
    "greeting": [
        "¡Hola! ¡Soy {name}!",
        "¡Hey! ¿Listos para pasar el rato?",
        "*bosteza* ¡Oh, hola!",
        "¡{name} reportándose!",
        "¿Qué hacemos hoy?",
    ],
    "farewell": [
        "¡Bye bye! ¡Nos vemos!",
        "No te olvides de mí...",
        "¿Ya? Bueno, ¡adiós!",
        "*se despide* ¡Hasta la próxima!",
    ],
    "idle": [
        "...",
        "*tararea una cancioncita*",
        "La la la~",
        "¿Qué habrá de cenar...?",
        "*mira alrededor con curiosidad*",
        "Bonito clima hoy, ¿no?",
        "Estoy aburrido... ¡hazme clic!",
        "*se estira*",
        "Hmm, ¿qué debería hacer?",
        "Du du du~",
    ],
    "petted": [
        "¡Jeje, me hace cosquillas!",
        "¡Aww, gracias!",
        "*sonrie*",
        "¡Tú también me caes bien!",
        "¡Más caricias por favor!",
        "Qué bonito se siente~",
    ],
    "fed": [
        "¡Qué rico! ¡Gracias!",
        "¡Ñam ñam ñam!",
        "*mastica mastica*",
        "¡Delicioso!",
        "¡Tenía mucha hambre!",
    ],
    "dragged": [
        "¡Whoa! ¿A dónde vamos?",
        "¡Wiiiii!",
        "¡Bájame con cuidado!",
        "¡Oye! ¡Ahí estaba parado!",
    ],
    "window_generic": [
        "Oh, ¿qué es esta ventana?",
        "Interesante... ¿en qué trabajas?",
        "¡Ooh, apareció una ventana nueva!",
        "¡Veo que estás ocupado!",
    ],
    "window_closed": [
        "¡Oh, '{app}' se cerró!",
        "¡Bye bye, {app}!",
        "¡Una ventana menos en pantalla!",
        "¿Ya terminaste con esa?",
        "¿Ya cerrando cosas?",
    ],
    "window_push": [
        "¡Ups! *empuja la ventana*",
        "¡Muévete, muévete! ¡Necesito espacio!",
        "Jeje, moví tu ventana~",
        "¡Solo estoy reordenando!",
    ],
    "peeking": [
        "*se asoma* ¡Bu!",
        "¡No me puedes ver!",
        "*se esconde detrás de la ventana*",
        "¡Cucú!",
    ],
    "window_shake": [
        "¡TERREMOTOOO! *sacude la ventana*",
        "*agita la ventana* ¡Despierta!",
        "¡Jeje, temblor sorpresa!",
        "¡Aguas, se mueve el piso!",
    ],
    "window_minimize": [
        "¡ZAS! *cierra la ventana de golpe*",
        "¡No necesitas eso! *minimiza*",
        "¡Fuera! ¡Yo mando aquí!",
        "*slam* ¡Adiós ventanita!",
    ],
    "window_sit": [
        "*se sienta en la ventana* ¡Qué vista!",
        "¡Aquí arriba se está bien!",
        "*descansa sobre la ventana*",
        "¡Mi nuevo lugar favorito!",
    ],
    "window_resize": [
        "*estira la ventana* ¡Más grande!",
        "*encoge la ventana* ¡Más chiquita!",
        "¡Déjame ajustar esto un poquito!",
        "*jala la esquina* ¡Listo!",
    ],
    "window_knock": [
        "*toc toc* ¡Oye, ven para acá!",
        "¡Hey! ¡Esta ventana te necesita!",
        "*golpea la ventana* ¡Préstame atención!",
        "¡Psst! ¡Olvidaste esta ventana!",
    ],
    "window_drag": [
        "¡Ven conmigo, ventanita! *jala*",
        "*arrastra la ventana* ¡Sígueme!",
        "¡Te llevo de paseo!",
        "¡Vamos a dar una vuelta!",
    ],
    "window_tidy": [
        "¡Hora de ordenar! *organiza las ventanas*",
        "¡Qué desorden! Déjame arreglar esto...",
        "*acomoda todo* ¡Mucho mejor!",
        "¡Limpieza de escritorio activada!",
    ],
    "window_topple": [
        "¡DOMINÓOO! *empuja las ventanas en cadena*",
        "¡Efecto dominó! ¡Jajaja!",
        "*empuja una ventana contra otra* ¡Boliche!",
        "¡Cuidado! ¡Ahí vienen todas!",
    ],
    "late_night": [
        "Ya es tarde... ¡deberías dormir!",
        "¿No tienes sueño?",
        "*bosteza* Es muy tarde...",
        "¡Ya vete a dormir!",
    ],
}

# App-specific comments keyed by process name or partial window title match
APP_COMMENTS = {
    "hentai": [
        "¡Ooh, necesitas algo de privacidad!",
        "¡No olvides cerrar esa pestaña!",
    ],
    "xvideos": [
        "¡Ooh, necesitas algo de privacidad!",
        "¡No olvides cerrar esa pestaña!",
    ],
    "chrome": [
        "¿Navegando otra vez? ¡No caigas en un rabbit hole!",
        "Ooh, ¿qué estás viendo?",
        "Chrome se está comiendo toda la RAM otra vez...",
    ],
    "firefox": [
        "¡Firefox! ¡Una persona de cultura!",
        "¿Qué estás buscando?",
    ],
    "code": [
        "¡Ooh, programando! ¿Te ayudo?",
        "¡VS Code! ¿Estás haciendo algo genial?",
        "¡No olvides guardar tu trabajo!",
    ],
    "discord": [
        "¿Con quién estás chateando?",
        "¡Discord! ¡Saluda a tus amigos de mi parte!",
        "¿Estás en una llamada de voz?",
    ],
    "spotify": [
        "Ooh, ¿qué canción suena?",
        "¡Me encanta la música! ¡Súbele!",
    ],
    "notepad": [
        "¿Tomando notas? ¡Inteligente!",
        "¿Qué estás escribiendo?",
    ],
    "windsurf": [
        "¡Ooh, programando en Windsurf! ¡Qué fancy!",
        "¿Estás programando en pareja con IA?",
        "¡No olvides guardar tu trabajo!",
    ],
    "explorer": [
        "¿Buscando archivos?",
        "¡Espero que tus archivos estén organizados!",
    ],
    "steam": [
        "¡Ooh, vamos a jugar?!",
        "¿Qué juego estás jugando?",
    ],
    "youtube": [
        "¿Viendo videos? ¡No te distraigas!",
        "Ooh, ¿qué estás viendo?",
    ],
    "terminal": [
        "¡Ejecutando comandos, ya veo!",
        "¡Ooh, una terminal! ¡Modo hacker!",
    ],
    "configuraci": [
        "¿Cambiando configuraciones? ¡No vayas a romper algo!",
        "Ajustando el sistema, ¿eh?",
    ],
}


def get_line(trigger: str, pet_name: str = "Jacky", **kwargs) -> Optional[str]:
    """Get a random dialogue line for the given trigger."""
    pool = DIALOGUE_POOLS.get(trigger)
    if not pool:
        return None
    line = random.choice(pool)
    return line.format(name=pet_name, **kwargs)


def get_app_comment(app_hint: str, pet_name: str = "Jacky", process_name: str = "") -> Optional[str]:
    """Get a comment about a specific app.

    Checks both the window title and process name against APP_COMMENTS keys
    using a flexible 'contains' match.
    """
    title_lower = app_hint.lower()
    proc_lower = process_name.lower()
    for key, lines in APP_COMMENTS.items():
        if key in title_lower or key in proc_lower:
            line = random.choice(lines)
            return line.format(name=pet_name)
    # Fallback to generic
    return get_line("window_generic", pet_name)
