<div align="center">

# Calories Tracker

**Nutrición clara. Progreso medible. Hábitos sostenibles.**

Registra comidas y peso, entiende tus objetivos diarios y sigue tu evolución desde una interfaz pensada para móvil.

[![CI](https://github.com/Papito084/calories_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Papito084/calories_tracker/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## Descripción del proyecto

Calories Tracker es una aplicación web para llevar un seguimiento personal de la alimentación y el peso. Cada usuario puede definir un objetivo, obtener una estimación de calorías y macronutrientes diarios, registrar comidas manualmente o analizar una imagen con un proveedor de visión opcional, y revisar su historial desde el dashboard.

El backend es una API **FastAPI** que sirve también la interfaz web. Usa **SQLite** por defecto para desarrollo local y **PostgreSQL** en Render. La autenticación admite usuario y contraseña, además de acceso opcional con **Google OAuth**.

> Las estimaciones nutricionales y metabólicas son orientativas; no sustituyen el consejo de un profesional sanitario.

## Características principales

- 📊 Dashboard móvil con resumen diario de calorías y macronutrientes.
- 🥗 Registro, edición e historial de comidas y peso.
- 🎯 Cálculo de objetivos nutricionales según actividad y meta personal.
- 📷 Análisis opcional de imágenes con Gemini u OpenAI.
- 🔐 Cuentas con contraseñas protegidas mediante Argon2 y sesiones con cookie HttpOnly.
- 👤 Acceso opcional con Google OAuth y aislamiento de datos por usuario.
- 🗃️ SQLite para desarrollo y PostgreSQL administrado para producción.
- 🚀 Despliegue automatizable en Render y CI con GitHub Actions.

## Tecnologías

| Área | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| API y servidor | FastAPI, Uvicorn, Gunicorn |
| Validación | Pydantic |
| Persistencia | SQLite, PostgreSQL, psycopg |
| Autenticación | PyJWT, Passlib/Argon2, Authlib |
| Imágenes | Pillow |
| Interfaz | HTML, CSS y JavaScript servidos por FastAPI |
| Pruebas y calidad | pytest, Ruff |
| Despliegue | Render, GitHub Actions |

## Arquitectura y estructura

El proyecto mantiene una estructura modular sencilla en la raíz: cada módulo agrupa una responsabilidad clara y `main.py` compone la API y la interfaz. Para este tamaño, esa organización evita capas ceremoniales y mantiene las rutas fáciles de seguir; si el dominio crece, los módulos pueden extraerse gradualmente a paquetes `routers/`, `services/` y `repositories/`.

```text
calories_tracker/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Comprueba lint, compilación y pruebas en GitHub
├── static/
│   └── cal-tracker-welcome.svg    # Ilustración vectorial de bienvenida
├── tests/
│   ├── conftest.py                # Configuración aislada de la base de test
│   ├── test_auth_api.py           # Pruebas de autenticación y acceso
│   └── test_nutrition_calc.py     # Pruebas de cálculos nutricionales
├── .editorconfig                  # Reglas comunes de espacios y finales de línea
├── .env.example                   # Plantilla de configuración local sin secretos
├── .gitignore                     # Excluye secretos, bases locales y cachés
├── LICENSE                        # Licencia MIT
├── Procfile                       # Comando de arranque compatible con Render
├── README.md                      # Guía del proyecto
├── auth.py                        # Registro, login, JWT, cookies y Google OAuth
├── config.py                      # Configuración y validación de variables de entorno
├── database.py                    # Conexiones, esquema y operaciones SQLite/PostgreSQL
├── main.py                        # Aplicación FastAPI, endpoints e interfaz web
├── migrate_sqlite_to_postgres.py  # Copia datos locales a PostgreSQL
├── nutrition_calc.py              # Cálculo de BMR, gasto diario y macros
├── pyproject.toml                 # Configuración de Ruff y pytest
├── render.yaml                    # Blueprint de servicio y PostgreSQL para Render
├── requirements-dev.txt           # Dependencias de desarrollo y pruebas
├── requirements.txt               # Dependencias de ejecución
└── vision_service.py              # Integración opcional de análisis de imágenes
```

### Persistencia

- En local, si `DATABASE_URL` está vacía, SQLite crea `cal_ai.db` junto al proyecto (o usa `DATABASE_PATH`).
- En producción, `DATABASE_URL` selecciona PostgreSQL. En Render debe apuntar a la **Internal Database URL** de la base asociada.
- El esquema y las migraciones se inicializan al arrancar la aplicación.
- Las imágenes de comidas se almacenan como miniaturas JPEG en la base de datos, no como archivos originales.
- `migrate_sqlite_to_postgres.py` sirve para copiar una base local; el despliegue no importa esos datos automáticamente.

## Requisitos previos

- Python **3.10 o posterior**.
- Git.
- Para el escaneo de comida, una clave de Gemini o de OpenAI (opcional).
- Para inicio de sesión con Google, credenciales OAuth de una aplicación web de Google (opcional).

## Instalación y uso rápido

### Windows (PowerShell)

Desde la carpeta raíz del repositorio:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Genera un secreto JWT local y añádelo al archivo `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Pega el resultado como valor de `JWT_SECRET` dentro de `.env`. No uses ni publiques un secreto compartido. Después inicia el servidor:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Abre [http://127.0.0.1:8001](http://127.0.0.1:8001). La documentación interactiva de la API está en [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Añade el secreto generado a `.env` como `JWT_SECRET` y ejecuta:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

## Variables de entorno

Configura estas variables en `.env` para desarrollo y en el apartado **Environment** del servicio para producción. `.env` está excluido de Git; usa `.env.example` como plantilla.

| Variable | Obligatoria | Descripción |
|---|---:|---|
| `JWT_SECRET` | Sí | Secreto aleatorio de al menos 32 caracteres para firmar tokens y sesiones. En Render, genera un valor privado. |
| `DATABASE_URL` | No | URL PostgreSQL. Si no se define, la aplicación usa SQLite. |
| `DATABASE_PATH` | No | Ubicación del SQLite local; por defecto, `cal_ai.db` junto al código. |
| `COOKIE_SECURE` | No | Usa `true` bajo HTTPS; Render lo configura como `true`. |
| `GOOGLE_CLIENT_ID` | No | ID de cliente OAuth; al configurarlo junto con el secreto se habilita el acceso con Google. |
| `GOOGLE_CLIENT_SECRET` | No | Secreto privado del cliente OAuth de Google. Nunca lo publiques. |
| `GOOGLE_REDIRECT_URI` | No | Callback OAuth; normalmente `https://<dominio>/auth/google/callback`. |
| `GEMINI_API_KEY` | No | Habilita el análisis de imágenes con Gemini. |
| `OPENAI_API_KEY` | No | Proveedor alternativo para análisis de imágenes con OpenAI. |
| `CORS_ORIGINS` | No | Orígenes permitidos separados por comas; déjalo vacío si la interfaz se sirve desde esta misma app. |
| `PORT` | No | Puerto HTTP; localmente usa `8001`, Render lo proporciona automáticamente. |

El análisis de imágenes necesita al menos una clave de IA; el resto de la aplicación funciona sin ellas. No añadas secretos a GitHub, incidencias, capturas ni mensajes.

## API

Los endpoints de perfil, dashboard, comidas, peso y escaneo requieren una sesión válida (cookie HttpOnly o token Bearer).

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/register` | Crear una cuenta local |
| `POST` | `/api/login` | Iniciar sesión con usuario y contraseña |
| `GET` | `/auth/google` | Iniciar el flujo OAuth opcional |
| `GET` | `/auth/google/callback` | Callback OAuth de Google |
| `GET` | `/api/auth/google/status` | Indica si Google OAuth está configurado |
| `GET` | `/api/dashboard` | Resumen, comidas y pesos del usuario |
| `GET` / `POST` | `/api/profile` | Leer y guardar el perfil nutricional |
| `POST` | `/api/onboard-profile` | Guardar perfil inicial del cuestionario |
| `POST` | `/api/scan-food` | Analizar una imagen JPEG, PNG o WebP (máx. 5 MB) |
| `POST` | `/api/log-meal` | Registrar una comida |
| `PUT` / `DELETE` | `/api/meal/{meal_id}` | Editar o eliminar una comida propia |
| `POST` | `/api/weight` | Registrar peso |
| `GET` | `/api/weight-history` | Consultar historial de peso |
| `POST` | `/api/reset-profile` | Eliminar los datos de perfil del usuario |

En local, explora los esquemas y prueba solicitudes desde `/docs`.

## Inicio de sesión con Google

1. En Google Cloud Console, configura la pantalla de consentimiento y crea un cliente OAuth de tipo **Web application**.
2. En **Authorized redirect URIs**, añade `https://<dominio-de-render>/auth/google/callback`.
3. En Render → servicio web → **Environment**, configura `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_REDIRECT_URI` con esa misma URL de callback.
4. Guarda los cambios y espera a que Render termine el despliegue.
5. Si la pantalla de consentimiento está en modo **Testing**, añade las cuentas que probarán el acceso como usuarios de prueba.

Solo se aceptan identidades con correo verificado por Google. El primer acceso crea una cuenta separada: no fusiona ni transfiere automáticamente los datos de una cuenta local que comparta el correo.

## Despliegue en Render

El repositorio incluye `render.yaml` con el comando de instalación y arranque, variables de entorno, servicio web y PostgreSQL. Puedes usar **New → Blueprint** para que Render lea el archivo; revisa región y coste del plan de la base antes de confirmar. El Blueprint incluido declara Oregon; si tu servicio y base actuales están en Frankfurt, conserva su configuración actual y asegúrate de que `DATABASE_URL` use la conexión interna de esa base. Evita renombrar o recrear la base ya asociada a producción.

La web necesita:

- `DATABASE_URL`: URL interna de PostgreSQL de Render.
- `JWT_SECRET`: secreto seguro de al menos 32 caracteres.
- `COOKIE_SECURE=true`: cookies seguras bajo HTTPS.
- Credenciales de Google o IA solo si vas a activar esas integraciones.

### Migrar datos SQLite existentes

Haz primero una copia de seguridad. Ejecuta la migración desde una máquina que tenga acceso de red a PostgreSQL, usando la **External Database URL** solo de forma local y temporal:

```powershell
$env:DATABASE_URL = "<URL externa privada de PostgreSQL>"
python migrate_sqlite_to_postgres.py --source ".\cal_ai.db"
```

El script no modifica SQLite y evita volver a insertar filas con el mismo ID. No pegues la URL en el código ni la subas al repositorio. El despliegue no copia los datos de SQLite por sí solo.

## Pruebas y calidad

Instala las dependencias de desarrollo si aún no lo has hecho:

```bash
pip install -r requirements-dev.txt
```

Ejecuta la suite y las comprobaciones estáticas:

```bash
pytest
ruff check .
python -m compileall -q auth.py config.py database.py main.py nutrition_calc.py vision_service.py
```

GitHub Actions ejecuta estas comprobaciones al abrir un pull request y al actualizar `main`. Las pruebas usan una base SQLite temporal y no conectan con datos de producción ni con proveedores de IA.

## Contribuir

1. Abre una incidencia para describir el problema o la mejora.
2. Crea una rama desde `main` y mantén los cambios enfocados.
3. Añade o actualiza pruebas para el comportamiento modificado.
4. Ejecuta `pytest`, `ruff check .` y la compilación antes de abrir el pull request.
5. No incluyas `.env`, credenciales, bases de datos reales, datos personales ni imágenes de usuarios.

## Licencia

Distribuido bajo la licencia **MIT**. Consulta el archivo [LICENSE](LICENSE).

---

<div align="center">
Hecho para convertir pequeños hábitos en progreso sostenible.
</div>
