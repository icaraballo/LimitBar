# LimitBar

Monitor de los límites de uso de mis IAs: Claude, Gemini y Antigravity (y más adelante ChatGPT…).
Un recolector en el Mac lee cuánto llevo gastado de cada una, lo guarda en un formato JSON propio
y lo sube a Supabase; una app en la barra de menú del Mac lo enseña. Después, widget de Android.

## Ejecutar

Requiere Python 3.10+ y sin dependencias externas. Cada IA necesita su sesión:

- **Claude**: haber iniciado sesión en Claude Code.
- **Gemini**: Google Chrome y, la primera vez (y cuando caduque la cookie de Google, cada varias
  semanas), `python3 -m collector.providers.gemini --login`: abre un Chrome con un perfil propio
  de LimitBar (`~/Library/Application Support/LimitBar/chrome-gemini/`, fuera del repo) para iniciar sesión; después se cierra con ⌘Q.
- **Antigravity**: tenerlo instalado con sesión iniciada (`agy`). No hace falta que esté abierto.

```sh
python3 -m collector.main              # imprime el uso, escribe data/latest.json y sube a Supabase
python3 -m collector.main --no-upload  # solo local
python3 -m unittest                    # tests
```

La primera vez, macOS pedirá permiso para que `security` lea la entrada
«Claude Code-credentials» del Llavero.

## Supabase

1. Crea un proyecto en [supabase.com](https://supabase.com) y ejecuta
   `supabase/migrations/001_tablas.sql` en el SQL Editor.
2. Guarda la URL del proyecto y la **clave secreta** (Project Settings → API Keys) en el Llavero:

   ```sh
   security add-generic-password -a limitbar -s limitbar-supabase-url -w 'https://xxxx.supabase.co'
   security add-generic-password -a limitbar -s limitbar-supabase-key -w   # la pide sin mostrarla
   ```

Con la CLI de Supabase la clave se obtiene con
`supabase projects api-keys --project-ref <ref> --reveal` (sin `--reveal` sale enmascarada y
Supabase responde 401). Sin esas dos entradas el recolector funciona igual, pero no sube nada.

Tablas: `latest_status` (una fila por proveedor; si un proveedor falla se conserva su última
lectura buena) y `usage_history` (una fila por ventana y ronda). Las dos tienen RLS sin
políticas: con la clave pública no se puede leer ni escribir nada.

## Ejecución automática

```sh
scripts/launchd.sh install    # cada 20 min (y al iniciar sesión); lanza una ronda ya
scripts/launchd.sh status     # ¿está cargado? + últimas líneas del log
scripts/launchd.sh uninstall
```

Log en `~/Library/Logs/LimitBar/collector.log`. Si el Mac duerme, la ronda pendiente se hace
al despertar.

## App del Mac (LimitBar.app)

App nativa en SwiftUI (`mac/`) que vive en la barra de menú, sin icono en el Dock. Se compila
sin Xcode, con las Command Line Tools:

```sh
scripts/build_app.sh install   # compila, copia a /Applications y la abre
```

Lee `data/latest.json` cada 30 s (la ruta del repo va grabada en su Info.plist), así que no
llama a ninguna API. «Actualizar ahora» lanza `scripts/collect.sh`. Tiene «Abrir al iniciar
sesión» y «Salir» (⌘Q).

## Barra de menú con SwiftBar (anterior)

Con [SwiftBar](https://github.com/swiftbar/SwiftBar) (`brew install --cask swiftbar`):

```sh
defaults write com.ameba.SwiftBar PluginDirectory -string "$PWD/menubar/swiftbar"
open -a SwiftBar
```

El plugin (`menubar/swiftbar/limitbar.1m.py`) relee `data/latest.json` cada minuto; no llama a
ninguna API. Arriba enseña la ventana más gastada de todas (ámbar ≥ 70 %, rojo ≥ 90 %, ⏸ si los
datos tienen más de 45 min). La lógica está en `menubar/render.py` y recorre cualquier
proveedor y ventana del JSON, así que los nuevos aparecen solos.

## Cómo funciona

- `collector/schema.py`: el formato JSON v0 (el contrato con el móvil).
- `collector/providers/`: un lector por proveedor; cada uno traduce sus datos a ese formato.
  Si uno falla, sale con `status: "error"` y los demás siguen.
- `collector/providers/claude.py`: lee el token OAuth de Claude Code (solo en memoria, solo
  lectura; nunca lo refresca) y consulta el endpoint de uso, que no es oficial.
- `collector/providers/gemini.py`: abre `gemini.google.com/usage` en un Chrome invisible con el
  perfil de LimitBar y lee el texto de la página (sesión de 5 h y semanal).
- `collector/providers/antigravity.py`: pregunta la cuota por grupo (Gemini 5 h/semanal, Claude
  5 h/semanal y Argon 4 semanal) al servidor local de Antigravity; si está cerrado, arranca un
  momento su propio `agy --hub`, que es quien renueva su sesión.
- `collector/usage_tokens.py`: tokens por modelo de los registros locales de Claude Code y de
  Antigravity, valorados con `collector/prices.py` («coste equivalente»).

## Estado

v0: Claude, Gemini y Antigravity en el recolector, subida a Supabase, ejecución automática con
launchd y app del Mac. Falta: widget de Android y el resto de proveedores.
