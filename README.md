# API de Solicitudes Académicas

API REST en **FastAPI** que registra solicitudes de estudiantes, las guarda en **Google Sheets** (vía una cuenta de servicio de Google Cloud) y avisa por **Telegram** cada vez que llega una nueva. Incluye una página web, un script de pruebas de carga y una versión mejorada para comparar resultados.

```
Usuario → Página web / API FastAPI → Procesamiento → Excel Online
                                                   → Bot de Telegram
```


## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/solicitudes` | Registra una solicitud, la guarda en Google Sheets y notifica por Telegram |
| GET | `/solicitudes` | Lista todas las solicitudes |
| GET | `/solicitudes/{id}` | Consulta una solicitud |
| PUT | `/solicitudes/{id}` | Cambia el estado (`Pendiente`, `En proceso`, `Resuelta`, `Rechazada`) |
| GET | `/stats` | Contadores de éxitos y errores de Google Sheets y Telegram (evidencia para las pruebas) |
| GET | `/health` | Estado y modo de la API |
| GET | `/docs` | Documentación interactiva (Swagger) |
| GET | `/` | Página web con formulario y lista |

Ejemplo:
```bash
curl -X POST http://localhost:8000/solicitudes -H "Content-Type: application/json" \
  -d '{"estudiante":"Ana Pérez","correo":"ana@correo.edu.co","tipo":"Certificación","descripcion":"Certificado de notas"}'
```

## 1. Instalación

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Linux/Mac: cp .env.example .env
```

## 2. Preparar Google Sheets

1. Crea una hoja de cálculo en Google Sheets (p. ej. **Solicitudes_Academicas**).
2. En la fila 1 de la pestaña escribe estos encabezados, **exactamente**: `ID | Fecha | Estudiante | Correo | Tipo | Descripcion | Estado`.
3. En [Google Cloud Console](https://console.cloud.google.com/) crea (o usa) un proyecto, y habilita las APIs **Google Sheets API** y **Google Drive API**.
4. Ve a **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**. Crea la cuenta y descarga su clave en formato **JSON**.
5. Guarda ese archivo JSON en la carpeta del proyecto (p. ej. como `credentials.json`). **Nunca lo subas a GitHub** (ver sección Seguridad).
6. Comparte tu hoja de cálculo con el correo de la cuenta de servicio (termina en `...iam.gserviceaccount.com`, está dentro del JSON) dándole rol de **Editor**, igual que si fuera un colaborador más.
7. Rellena en `.env`: `GOOGLE_CREDENTIALS_FILE` (nombre del archivo JSON), `GOOGLE_SHEET_ID` (el ID que aparece en la URL de la hoja, entre `/d/` y `/edit`) y `GOOGLE_SHEET_NAME` (el nombre de la pestaña, p. ej. `Hoja 1`).

## 3. Crear el Bot de Telegram

1. En Telegram habla con **@BotFather** → `/newbot` → copia el token → `TELEGRAM_BOT_TOKEN`.
2. Abre tu bot y envíale cualquier mensaje (o agrégalo a un grupo y escribe allí).
3. Visita `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia `chat.id` → `TELEGRAM_CHAT_ID`. **Ojo:** este número debe ser distinto al ID del propio bot (el que aparece antes de los dos puntos en el token).

## 4. Ejecutar

```bash
uvicorn app.main:app --reload
```
Abre <http://localhost:8000> (web) o <http://localhost:8000/docs> (Swagger).

**Sin credenciales** puedes practicar con `SIMULAR=true`: Google Sheets y Telegram se simulan en memoria. Sirve para desarrollar, **no** como evidencia: el informe debe usar los servicios reales.

## 5. Pruebas de carga

Con la API corriendo (idealmente ya publicada):

```bash
python scripts/prueba_carga.py --url https://TU-APP.onrender.com --n 10 25 50 100 --etiqueta base
```
El script lanza N solicitudes simultáneas y muestra tiempo medio, p95 y máximo, exitosas, errores, códigos HTTP y los contadores de Google Sheets y Telegram. Guarda todo en `resultados_carga.csv`.

Después de cada prueba revisa en Google Sheets cuántas filas llegaron y en Telegram cuántos mensajes recibiste; compáralos con los contadores.

## 6. Versión mejorada (antes / después)

Cambia en `.env` (o en las variables del servicio publicado) `MODO=mejorado` y repite la prueba con `--etiqueta mejorada`.

| | `MODO=simple` | `MODO=mejorado` |
|---|---|---|
| Respuesta al usuario | Espera a Google Sheets y a Telegram (201) | Inmediata, procesa en segundo plano (202) |
| Escritura en Google Sheets | Una llamada por solicitud | Lotes de hasta 25 filas por llamada |
| Errores 429 / 5xx | Se pierden | Reintentos con espera creciente y respeto de `Retry-After` |
| Telegram | Un mensaje por solicitud | Mensajes agrupados con pausa entre envíos |
| Lecturas | Siempre consulta Google Sheets | Caché de 5 s |

En modo mejorado `t_hasta_procesar_todo_s` indica cuánto tardó realmente en terminar Google Sheets y Telegram, más allá de la respuesta rápida al usuario.

## 7. Publicar

Ejemplo con **Render** (gratuito): crea un *Web Service* desde tu repositorio de GitHub.
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- En *Environment* agrega las variables de `.env.example` con sus valores reales (MODO, SIMULAR, GOOGLE_SHEET_ID, GOOGLE_SHEET_NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, etc).
- El archivo de credenciales de Google (`credentials.json`) **no se sube a GitHub**: en Render se añade como *Secret File* (Settings → Secret Files), con la ruta `/etc/secrets/credentials.json`, y se ajusta `GOOGLE_CREDENTIALS_FILE=/etc/secrets/credentials.json` en las variables de entorno.

El plan gratuito se duerme tras un rato sin uso; haz una petición a `/health` antes de la sustentación.

## Seguridad

- `.env` y `credentials.json` están en `.gitignore`: **nunca** subas tokens, secretos, contraseñas ni la clave de la cuenta de servicio de Google.
- Si un secreto se filtra, revócalo y crea uno nuevo (BotFather: `/revoke`; Google Cloud: elimina la clave de la cuenta de servicio y genera una nueva).
- La API no tiene autenticación de usuarios, es suficiente para esta actividad pero no para producción.
- Las celdas que empiezan con `=`, `+`, `-` o `@` se neutralizan para evitar inyección de fórmulas en la hoja de cálculo.

## Estructura

```
app/main.py endpoints, colas y trabajadores del modo mejorado
app/services.py conectores de Google Sheets y Telegram, reintentos y contadores
app/models.py validación de datos
app/config.py variables de entorno
app/static/ página web
scripts/prueba_carga.py

```