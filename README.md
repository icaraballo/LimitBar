# LimitBar

Monitor de los límites de uso de mis IAs (Claude, y más adelante Gemini, Antigravity, ChatGPT…).
Un recolector en el Mac lee cuánto llevo gastado de cada una y lo guarda en un formato JSON
propio; después irá a Supabase y a un widget de Android.

## Ejecutar

Requiere Python 3.10+ y haber iniciado sesión en Claude Code. Sin dependencias externas.

```sh
python3 -m collector.main     # imprime el uso y escribe data/latest.json
python3 -m unittest           # tests
```

La primera vez, macOS pedirá permiso para que `security` lea la entrada
«Claude Code-credentials» del Llavero.

## Cómo funciona

- `collector/schema.py`: el formato JSON v0 (el contrato con el móvil).
- `collector/providers/`: un lector por proveedor; cada uno traduce sus datos a ese formato.
  Si uno falla, sale con `status: "error"` y los demás siguen.
- `collector/providers/claude.py`: lee el token OAuth de Claude Code (solo en memoria, solo
  lectura; nunca lo refresca) y consulta el endpoint de uso, que no es oficial.

## Estado

v0: Claude (ventanas de 5 h, semanal y semanales por modelo). Falta: ejecución automática,
Supabase, widget y el resto de proveedores.
