# Calories Tracker

API de seguimiento de calorías y nutrición con FastAPI. Incluye perfiles por usuario, registro de comidas y peso, cálculo de objetivos y análisis opcional de imágenes con Gemini o OpenAI.

## Desarrollo local (Windows)

Requiere Python 3.10 o posterior. SQLite se usa automáticamente cuando no se configura `DATABASE_URL`; el archivo se crea junto al proyecto como `cal_ai.db` o en la ruta definida por `DATABASE_PATH`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:JWT_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
uvicorn main:app --reload
```

El servidor local abre en `http://127.0.0.1:8001` si se configura `PORT=8001`; la API interactiva está en `/docs`. También puedes guardar el secreto generado en `.env` como `JWT_SECRET`. No uses un secreto de ejemplo en producción.

Variables opcionales:

- `DATABASE_PATH`: ruta del archivo SQLite.
- `GEMINI_API_KEY` y `OPENAI_API_KEY`: proveedores de análisis de comida (Gemini se intenta primero).
- `COOKIE_SECURE`: `true` cuando se sirve por HTTPS; en Render ya está habilitado.
- `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`: credenciales OAuth de Google; al configurarlas aparece la opción “Continuar con Google”.
- `GOOGLE_REDIRECT_URI`: URI de callback opcional; si se deja vacía, se calcula usando el dominio de la solicitud.
- `CORS_ORIGINS`: lista separada por comas de los orígenes web externos autorizados. Déjala vacía para el uso desde el mismo origen.

## Despliegue en Render

`render.yaml` configura un servicio web y una base de datos PostgreSQL administrada; Render conecta `DATABASE_URL` y genera `JWT_SECRET`. El plan de PostgreSQL indicado puede tener coste. Introduce las claves de Gemini/OpenAI en el panel de variables de entorno si quieres activar el análisis de imágenes. No se usa SQLite en producción cuando `DATABASE_URL` está definida.

La app crea el esquema al iniciar. Si ya tienes datos locales en `cal_ai.db`, desplegar PostgreSQL no los copia automáticamente; el archivo local permanece intacto. Para copiarlos desde tu PC, ejecuta el script desde PowerShell usando la URL externa de PostgreSQL de Render y habilitando el acceso de red necesario:

```powershell
$env:DATABASE_URL = "<URL externa de PostgreSQL>"
python migrate_sqlite_to_postgres.py --source ".\cal_ai.db"
```

El proceso no modifica el archivo SQLite y se puede repetir sin duplicar filas con el mismo ID. Haz primero una copia de seguridad y comprueba el recuento de datos antes de cambiar el tráfico de producción. Mantén `DATABASE_URL` privada y no la guardes en el repositorio.

### Acceso con Google

1. En Google Cloud Console, crea un proyecto, configura la pantalla de consentimiento OAuth y crea un cliente OAuth de tipo **Web application**.
2. En **Authorized redirect URIs**, añade `https://tu-servicio.onrender.com/auth/google/callback` (reemplaza el dominio por el tuyo).
3. En el servicio web de Render → **Environment**, añade `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` con los valores del cliente OAuth, y `GOOGLE_REDIRECT_URI` con exactamente la URI de callback anterior.
4. Guarda los cambios y espera a que Render redepliegue el servicio. La bienvenida mostrará “Continuar con Google”.

Si la pantalla de consentimiento sigue en modo **Testing**, añade tu cuenta de Google como usuario de prueba en Google Cloud Console.

La aplicación solo acepta cuentas con correo verificado por Google y guarda su identificador estable para futuras entradas. Una primera entrada crea una cuenta separada y continúa al cuestionario; no se fusiona automáticamente con una cuenta previa aunque use el mismo correo. Las claves OAuth son secretos: no las subas a GitHub ni las compartas.

## Autenticación y datos

- Los endpoints de perfil, comidas, peso, escaneo y reinicio requieren autenticación.
- El registro exige contraseñas de al menos 12 caracteres.
- La app muestra una bienvenida de pantalla completa al no detectar una sesión válida. El registro inicia el cuestionario de perfil y, al completarlo, abre el dashboard; iniciar sesión lleva al dashboard existente.
- Las contraseñas se almacenan con Argon2; los hashes SHA-256 Crypt existentes se actualizan al iniciar sesión correctamente.
- El token de sesión se establece en una cookie HttpOnly, SameSite=Lax, con vencimiento de un día. Las respuestas de autenticación también incluyen el token para clientes API.
- Los datos de cada cuenta se consultan, modifican y eliminan por `user_id`.
- Las imágenes aceptadas son JPEG, PNG o WebP de hasta 5 MB. En la base se conserva una miniatura JPEG, no el original.

## Comprobaciones

```powershell
python -m compileall auth.py config.py database.py main.py nutrition_calc.py vision_service.py
```

El escaneo de comida necesita una clave de Gemini u OpenAI; el resto de la app funciona sin esas claves.

## Licencia

MIT © Papito084
