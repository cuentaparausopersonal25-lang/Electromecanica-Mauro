# Electromecánica Mauro

Plataforma educativa Flask con tres capítulos, registro de estudiantes, seguimiento básico, evaluaciones, dos roles administrativos y recepción segura de archivos de actualización.

## 1. Archivos y carpetas

- `app.py`: servidor, base de datos, autenticación y rutas.
- `templates/`: páginas HTML.
- `static/css/style.css`: diseño adaptable.
- `static/js/main.js`: interacciones pequeñas.
- `uploads/videos/`: videos cargados desde el panel.
- `uploads/updates/`: archivos recibidos para revisión.
- `requirements.txt` y `Procfile`: instalación y arranque.

## 2. Configurar administradores

En Render > servicio > Environment, crear estas cuatro variables (usar contraseñas largas y únicas):

- `OWNER_USERNAME` = usuario del propietario
- `OWNER_PASSWORD` = contraseña del propietario
- `ADMIN2_USERNAME` = usuario del segundo administrador
- `ADMIN2_PASSWORD` = contraseña del segundo administrador

Las cuentas se crean al iniciar la aplicación si esas variables están configuradas. Si cambiás las contraseñas luego de crear las cuentas, el cambio no se aplica automáticamente a las cuentas ya existentes; para cambiar credenciales se necesita un flujo de cambio de contraseña o una actualización controlada de la base.

El propietario puede crear/eliminar capítulos y acceder a respaldos y recepción de archivos de actualización. El segundo administrador puede administrar capítulos, clases y preguntas, pero no puede entrar a actualización ni descargar respaldos. Ningún administrador puede administrar usuarios desde esta primera versión.

## 3. Publicar en Render

1. Subí el contenido completo de esta carpeta a la raíz de un repositorio GitHub.
2. En Render, creá un servicio **Web Service** conectado al repositorio.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. En Environment agregá las cuatro variables de administradores y `SECRET_KEY` (valor aleatorio largo).
6. Para conservar base de datos y videos entre despliegues, configurá un **Persistent Disk** en `/var/data` y las variables `DATA_DIR=/var/data`, `UPLOAD_DIR=/var/data/uploads`. El archivo `render.yaml` propone esa configuración; verificá el costo y disponibilidad del disco en tu plan antes de aplicarlo.

## 4. Ejecutar en Windows

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set OWNER_USERNAME=propietario
set OWNER_PASSWORD=una-clave-larga
set ADMIN2_USERNAME=admin2
set ADMIN2_PASSWORD=otra-clave-larga
set SECRET_KEY=una-clave-larga-y-aleatoria
py app.py
```

Abrí `http://127.0.0.1:5000`.

## 5. Funciones y límites importantes

- Los estudiantes pueden registrarse, ver cursos, marcar clases completadas, rendir cuestionarios y consultar resultados.
- Los administradores crean clases y preguntas de opción múltiple desde `/admin`.
- Los videos se aceptan en MP4, WEBM, OGG o MOV. Se guardan en el almacenamiento configurado; en Render necesitás disco persistente u otro almacenamiento de objetos para no perderlos al reiniciar o desplegar.
- La sección «Actualizar plataforma» permite al propietario recibir y conservar archivos ZIP/TXT/MD/JSON/PDF para revisión. **No instala ni ejecuta código automáticamente**, deliberadamente. Aplicar código recibido como ZIP directamente desde una web sería un riesgo de seguridad; las actualizaciones de la aplicación se publican mediante GitHub/Render.
- El registro de estudiantes es público en esta versión. Los resultados y el progreso se asocian a la cuenta iniciada.
- Para producción se recomienda HTTPS (Render lo proporciona), respaldos regulares, límites de tamaño adecuados y almacenamiento externo para muchos videos.
- La app incluye un respaldo descargable de base de datos y videos desde el panel del propietario.

## 6. Seguridad

Las contraseñas se guardan con hash seguro, las rutas administrativas validan el rol en el servidor y los nombres de archivos se sanitizan. No compartas las contraseñas ni el valor de `SECRET_KEY`.
