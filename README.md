<div align="center">

# Calories Tracker

**Nutrición clara. Progreso medible. Hábitos sostenibles.**

Registra comidas y peso, entiende tus objetivos diarios y sigue tu evolución desde una aplicación web adaptable a móviles.

[![CI](https://github.com/Papito084/calories_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Papito084/calories_tracker/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## Descripción

Calories Tracker es una aplicación web para llevar un seguimiento personal de la alimentación, las calorías y el peso. Cada usuario puede definir objetivos, registrar comidas, analizar imágenes de alimentos con un proveedor de visión opcional y revisar su evolución desde un dashboard adaptable.

El backend es una API **FastAPI** que sirve también la interfaz web. La autenticación admite usuario y contraseña, además de inicio de sesión opcional con **Google OAuth**. En local utiliza **SQLite** y en producción puede conectarse a **PostgreSQL**.

> Las estimaciones nutricionales y metabólicas son orientativas; no sustituyen el consejo de un profesional sanitario.

## Características

- 📊 Dashboard adaptable con resumen diario de calorías y macronutrientes.
- 🥗 Registro, edición e historial de comidas y peso.
- 🎯 Objetivos nutricionales personalizados según actividad y meta.
- 📷 Análisis opcional de imágenes con Gemini o OpenAI.
- 🔐 Autenticación segura con contraseñas protegidas y cookies HttpOnly.
- 👤 Inicio de sesión opcional con Google y datos aislados por usuario.
- 🗃️ SQLite para desarrollo y PostgreSQL para producción.
- ✅ Pruebas automatizadas y CI con GitHub Actions.

## Tecnologías

| Área | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| API y servidor | FastAPI, Uvicorn, Gunicorn |
| Validación | Pydantic |
| Persistencia | SQLite, PostgreSQL, psycopg |
| Autenticación | PyJWT, Passlib/Argon2, Authlib |
| Imágenes | Pillow |
| Interfaz | HTML, CSS y JavaScript |
| Calidad | pytest, Ruff, GitHub Actions |
| Despliegue | Render |

## Arquitectura

El backend se agrupa en `app/`, con módulos pequeños por responsabilidad. Las pruebas, documentación, recursos estáticos y automatización viven en sus propias carpetas; los archivos de configuración de herramientas y despliegue permanecen en la raíz para que Render y GitHub Actions los detecten sin configuración adicional.

```text
calories_tracker/
├── .github/
│   └── workflows/
│       └── ci.yml                  # Calidad y pruebas en cada cambio
├── app/
│   ├── static/
│   │   └── cal-tracker-welcome.svg # Ilustración de bienvenida
│   ├── __init__.py
│   ├── auth.py                     # Registro, sesión y Google OAuth
│   ├── config.py                   # Configuración y variables de entorno
│   ├── database.py                 # Esquema y operaciones SQLite/PostgreSQL
│   ├── main.py                     # API FastAPI e interfaz web
│   ├── migrate_sqlite_to_postgres.py
│   ├── nutrition_calc.py            # Cálculos de nutrición
│   └── vision_service.py            # Proveedores de análisis de imágenes
├── docs/
│   └── RUNDEMO.md                  # Instalación, configuración y ejecución
├── tests/
│   ├── conftest.py
│   ├── test_auth_api.py
│   └── test_nutrition_calc.py
├── .env.example
├── .gitignore
├── Procfile
├── README.md
├── pyproject.toml
├── render.yaml
├── requirements-dev.txt
└── requirements.txt
```

## Datos y persistencia

- En local, si `DATABASE_URL` está vacía, SQLite utiliza `cal_ai.db` en la raíz del repositorio (o la ruta indicada en `DATABASE_PATH`).
- En producción, `DATABASE_URL` selecciona PostgreSQL; en Render se recomienda utilizar la URL interna de la base asociada.
- El esquema y sus migraciones se inicializan al arrancar la aplicación.
- Las imágenes de comidas se guardan como miniaturas JPEG en la base de datos, no como archivos originales.
- El despliegue no copia automáticamente los datos que hubiera en una base SQLite local.

## API

Las rutas de cuenta, perfil, comidas, peso y análisis de imágenes requieren autenticación.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/register` | Crear una cuenta local |
| `POST` | `/api/login` | Iniciar sesión |
| `GET` | `/auth/google` | Iniciar OAuth opcional |
| `GET` | `/api/dashboard` | Resumen y actividad del usuario |
| `GET` / `POST` | `/api/profile` | Leer y guardar el plan nutricional |
| `GET` / `PUT` | `/api/account-profile` | Consultar y editar la cuenta |
| `POST` | `/api/scan-food` | Analizar una imagen de comida |
| `POST` | `/api/log-meal` | Registrar una comida |
| `PUT` / `DELETE` | `/api/meal/{meal_id}` | Editar o eliminar una comida |
| `POST` | `/api/weight` | Registrar un peso |
| `GET` | `/api/weight-history` | Consultar el historial de peso |

## Guía de instalación y uso

Para preparar el entorno, configurar las variables de entorno, ejecutar la app, realizar pruebas, iniciar sesión con Google, desplegar en Render o migrar datos, consulta la guía detallada:

**[Abrir la guía RUNDEMO](docs/RUNDEMO.md)**.

## Contribuir

Consulta la sección de contribución de [RUNDEMO.md](docs/RUNDEMO.md). No incluyas secretos, bases de datos reales ni datos personales en cambios o incidencias.

## Licencia

Distribuido bajo la licencia **MIT**. Consulta [LICENSE](LICENSE).

---

<div align="center">
Hecho para convertir pequeños hábitos en progreso sostenible.
</div>
