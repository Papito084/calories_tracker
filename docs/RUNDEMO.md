# RUNDEMO: instalación y puesta en marcha

Esta guía explica cómo preparar, ejecutar, probar y desplegar Calories Tracker. Los comandos deben ejecutarse desde la raíz del repositorio, salvo que se indique lo contrario.

## Requisitos

- Python **3.10 o posterior**.
- Git.
- Una clave de Gemini u OpenAI solo si quieres analizar fotos.
- Credenciales OAuth de Google solo si quieres habilitar el acceso con Google.

## Preparar el entorno local

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Si PowerShell bloquea la activación del entorno virtual, puedes ejecutar los comandos con `.\.venv\Scripts\python.exe` sin activar el entorno.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
```

## Configurar variables de entorno

La aplicación lee `.env` desde la raíz del repositorio. Genera una clave privada para `JWT_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copia el resultado en `.env` como valor de `JWT_SECRET`. No lo compartas ni lo subas a GitHub.

| Variable | Requerida | Uso |
|---|---:|---|
| `JWT_SECRET` | Sí | Clave aleatoria de al menos 32 caracteres para las sesiones. |
| `DATABASE_URL` | No | Si se configura, conecta PostgreSQL; si no, se usa SQLite. |
| `DATABASE_PATH` | No | Ruta personalizada de SQLite; por defecto, `cal_ai.db` en la raíz. |
| `COOKIE_SECURE` | No | Debe ser `true` bajo HTTPS; Render lo configura así. |
| `GOOGLE_CLIENT_ID` | No | ID OAuth de Google; se configura junto con el secreto. |
| `GOOGLE_CLIENT_SECRET` | No | Secreto OAuth privado de Google. |
| `GOOGLE_REDIRECT_URI` | No | Callback, normalmente `https://<dominio>/auth/google/callback`. |
| `GEMINI_API_KEY` | No | Habilita análisis de imágenes con Gemini. |
| `GROQ_API_KEY` | No | Habilita Groq como alternativa si Gemini falla. |
| `OPENAI_API_KEY` | No | Habilita OpenAI como alternativa si los proveedores anteriores fallan. |
| `CORS_ORIGINS` | No | Orígenes web permitidos, separados por comas. |
| `PORT` | No | Puerto HTTP; por defecto, `8001` en local. |

La aplicación completa funciona sin claves de IA; solo se desactiva el análisis de fotos. Guarda las claves de producción en **Render → Environment**, no en el código ni en `.env` compartido.

## Ejecutar la aplicación

Desde la raíz y con el entorno activado:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Abre:

- Aplicación: [http://127.0.0.1:8001](http://127.0.0.1:8001)
- Documentación interactiva de la API: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)

Para probar desde otro dispositivo de tu red local, inicia el servidor con `--host 0.0.0.0` y abre en el móvil `http://<IP-local-del-ordenador>:8001`. No expongas este servidor de desarrollo directamente a Internet.

## Pruebas y calidad

Ejecuta desde la raíz del proyecto:

```bash
pytest
ruff check .
python -m compileall -q app
```

Las pruebas usan una base de datos SQLite temporal y no acceden a la base de producción ni a proveedores de IA. GitHub Actions ejecuta estos controles para los cambios de `main` y los pull requests.

## Configurar Google OAuth

1. En Google Cloud Console, configura la pantalla de consentimiento y crea un cliente OAuth de tipo **Web application**.
2. Añade `https://<dominio-de-render>/auth/google/callback` como URI de redirección autorizada.
3. En Render → servicio web → **Environment**, configura `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_REDIRECT_URI`.
4. Guarda los cambios y espera a que Render despliegue la nueva configuración.
5. Si el consentimiento está en modo **Testing**, añade como usuarios de prueba las cuentas de Google permitidas.

Solo se aceptan correos verificados por Google. La cuenta de Google no se fusiona automáticamente con una cuenta local existente.

## Desplegar en Render

El repositorio incluye `render.yaml` y un `Procfile` para el servicio web. Al conectar el Blueprint, revisa el nombre, la región y el coste de la base de datos antes de aplicarlo.

**Importante para instalaciones existentes:** el Blueprint de este repositorio puede no coincidir con la región de tu servicio y base ya desplegados. Si tu PostgreSQL está en Frankfurt, no recrees ni cambies de región esa base para seguir esta guía; conserva el servicio existente y comprueba que `DATABASE_URL` usa su conexión interna.

Variables habituales del servicio en producción:

- `DATABASE_URL`: URL interna de PostgreSQL en Render.
- `JWT_SECRET`: secreto privado, generado o configurado desde Render.
- `COOKIE_SECURE=true`: cookies seguras para HTTPS.
- `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`: solo si habilitas Google.
- `GEMINI_API_KEY`, `GROQ_API_KEY` o `OPENAI_API_KEY`: solo si habilitas el análisis de fotos. Se prueban en ese orden y los proveedores posteriores sirven como alternativa si falla uno anterior.

## Migrar una base SQLite a PostgreSQL

El despliegue no copia por sí solo una base local. Haz primero una copia de seguridad y ejecuta la migración desde un ordenador con acceso de red a PostgreSQL. Usa la **External Database URL** solo de forma temporal y privada.

### Windows (PowerShell)

```powershell
$env:DATABASE_URL = "<URL externa privada de PostgreSQL>"
python -m app.migrate_sqlite_to_postgres --source ".\cal_ai.db"
```

### macOS / Linux

```bash
export DATABASE_URL="<URL externa privada de PostgreSQL>"
python -m app.migrate_sqlite_to_postgres --source "./cal_ai.db"
```

El proceso no modifica SQLite y evita duplicar filas con el mismo ID. No pongas la URL en un archivo versionado, en un mensaje o en una incidencia.

## Contribuir

1. Abre una incidencia para describir el problema o la mejora.
2. Crea una rama desde `main` y mantén los cambios enfocados.
3. Añade o actualiza pruebas del comportamiento modificado.
4. Ejecuta `pytest`, `ruff check .` y `python -m compileall -q app`.
5. No incluyas `.env`, credenciales, bases de datos reales, datos personales ni imágenes de usuarios.
