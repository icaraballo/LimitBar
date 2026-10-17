# LimitBar

Monitor de los límites de uso de mis IAs (Claude, y más adelante Gemini, Antigravity, ChatGPT…).
Un recolector en el Mac lee cuánto llevo gastado de cada una y lo guarda en un formato JSON
propio; después irá a Supabase y a un widget de Android.

## Ejecutar

Requiere Python 3.10+ y haber iniciado sesión en Claude Code. Sin dependencias externas.

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

## Cómo funciona

- `collector/schema.py`: el formato JSON v0 (el contrato con el móvil).
- `collector/providers/`: un lector por proveedor; cada uno traduce sus datos a ese formato.
  Si uno falla, sale con `status: "error"` y los demás siguen.
- `collector/providers/claude.py`: lee el token OAuth de Claude Code (solo en memoria, solo
  lectura; nunca lo refresca) y consulta el endpoint de uso, que no es oficial.

## Estado

v0: Claude (ventanas de 5 h, semanal y semanales por modelo) y subida a Supabase. Falta:
ejecución automática, widget y el resto de proveedores.
