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

# App-specific comments organised by category.
# Each group has a list of keyword matchers and shared comment lines.
# The flat APP_COMMENTS lookup is auto-generated at the bottom.
_APP_GROUPS = {
    "work_communication": {
        "keywords": [
            "slack", "teams", "meet", "zoom", "webex", "skype",
        ],
        "comments": [
            "¿En una junta? ¡No te duermas!",
            "¿Reunión de trabajo? ¡Ánimo!",
            "¡Saluda a tus compañeros de mi parte!",
            "¿Otra llamada más? ¡Aguante!",
            "*se pone corbata* ¡Yo también soy profesional!",
        ],
    },
    "social_chat": {
        "keywords": [
            "discord", "whatsapp", "telegram", "messenger", "signal",
        ],
        "comments": [
            "¿Con quién estás chateando?",
            "¡Saluda a tus amigos de mi parte!",
            "¿Estás en una llamada?",
            "¡No te distraigas mucho platicando!",
            "¿Chismeando? ¡Cuéntame!",
        ],
    },
    "coding": {
        "keywords": [
            "code", "windsurf", "cursor", "netbeans", "notepad",
            "sublime", "intellij", "pycharm", "visual studio", "vim",
            "neovim", "eclipse", "rider", "webstorm", "android studio",
            "phpstorm", "goland", "fleet", "zed",
        ],
        "comments": [
            "¡Ooh, programando! ¿Te ayudo?",
            "¿Estás haciendo algo genial?",
            "¡No olvides guardar tu trabajo!",
            "¿Otro bug? ¡Tú puedes!",
            "¡Recuerda hacer commits seguido!",
            "*mira el código* No entiendo nada, ¡pero se ve cool!",
        ],
    },
    "browsers": {
        "keywords": [
            "chrome", "firefox", "edge", "opera", "brave", "vivaldi",
            "arc", "waterfox", "librewolf",
        ],
        "comments": [
            "¿Navegando otra vez? ¡No caigas en un rabbit hole!",
            "Ooh, ¿qué estás viendo?",
            "¡Cuidado con las pestañas! ¡Tienes como mil!",
            "¿Buscando algo interesante?",
            "¡El navegador se está comiendo toda la RAM!",
        ],
    },
    "media_players": {
        "keywords": [
            "vlc", "player", "mpv", "mpc", "plex", "kodi", "potplayer",
        ],
        "comments": [
            "¡Hora de ver algo! ¿Qué veremos?",
            "¿Película o serie?",
            "*se sienta con palomitas* ¡Estoy listo!",
            "¡Ooh, noche de cine!",
        ],
    },
    "music": {
        "keywords": [
            "spotify", "music", "deezer", "tidal", "soundcloud",
            "foobar", "audacity", "musicbee", "aimp",
        ],
        "comments": [
            "Ooh, ¿qué canción suena?",
            "¡Me encanta la música! ¡Súbele!",
            "*baila al ritmo*",
            "¡Ponme algo bueno!",
            "¿Me pasas la playlist?",
        ],
    },
    "gaming": {
        "keywords": [
            "steam", "epic", "ubisoft", "battle", "riot", "origin",
            "gog", "xbox", "geforce", "playnite", "ea app",
        ],
        "comments": [
            "¡Ooh, vamos a jugar?!",
            "¿Qué juego estás jugando?",
            "¡Hora de gaming! *agarra control*",
            "¡No te olvides de comer por estar jugando!",
            "¿Rankeds o casual?",
        ],
    },
    "terminals": {
        "keywords": [
            "cmd", "powershell", "terminal", "bash", "wsl", "mintty",
            "alacritty", "wezterm", "kitty", "hyper", "tabby",
        ],
        "comments": [
            "¡Ejecutando comandos, ya veo!",
            "¡Ooh, una terminal! ¡Modo hacker!",
            "sudo hazme un sandwich",
            "*teclea rápidamente* ¡Soy un hacker!",
            "¡Cuidado con lo que ejecutas!",
        ],
    },
    "file_management": {
        "keywords": [
            "explorer", "total commander", "7zip", "winrar", "everything",
        ],
        "comments": [
            "¿Buscando archivos?",
            "¡Espero que tus archivos estén organizados!",
            "¿Limpiando el disco duro?",
            "¡Cuidado con borrar algo importante!",
        ],
    },
    "video_streaming": {
        "keywords": [
            "youtube", "twitch", "netflix", "disney", "prime video",
            "hbo", "crunchyroll", "kick",
        ],
        "comments": [
            "¿Viendo videos? ¡No te distraigas!",
            "Ooh, ¿qué estás viendo?",
            "¡Solo un episodio más! ...¿verdad?",
            "¿Maratón? ¡Yo me apunto!",
        ],
    },
    "productivity": {
        "keywords": [
            "word", "excel", "powerpoint", "onenote", "outlook",
            "notion", "obsidian", "todoist", "trello", "asana",
        ],
        "comments": [
            "¡Qué productivo! ¡Sigue así!",
            "¿Trabajando duro o apenas duro trabajando?",
            "¡No olvides guardar! Ctrl+S es tu amigo.",
            "¡Tú puedes, ánimo con ese trabajo!",
        ],
    },
    "design": {
        "keywords": [
            "photoshop", "illustrator", "figma", "gimp", "blender",
            "canva", "inkscape", "premiere", "after effects", "davinci",
            "paint",
        ],
        "comments": [
            "¡Ooh, estás creando algo bonito!",
            "¿Diseñando? ¡Qué artista!",
            "¡A ver, dibújame a mí!",
            "*observa con admiración*",
        ],
    },
    "nsfw": {
        "keywords": [
            "hentai", "xvideos", "pornhub", "xnxx", "xxx", "rule34", "porn",
        ],
        "comments": [
            "¡Ooh, necesitas algo de privacidad!",
            "¡No olvides cerrar esa pestaña!",
            "...No vi nada, no vi nada.",
        ],
    },
    "settings": {
        "keywords": [
            "configuraci",
        ],
        "comments": [
            "¿Cambiando configuraciones? ¡No vayas a romper algo!",
            "Ajustando el sistema, ¿eh?",
        ],
    },
}

# Build flat keyword → comments lookup used by get_app_comment()
APP_COMMENTS = {}
for _group in _APP_GROUPS.values():
    for _kw in _group["keywords"]:
        APP_COMMENTS[_kw] = _group["comments"]


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
