# AI Song Detection

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

El inglés es el idioma principal del proyecto y el README en inglés es el documento de referencia; este archivo es su traducción al español, mientras que la interfaz y los comandos se mantienen en inglés.

Analiza música localmente para detectar indicios de generación con IA mediante una interfaz web, una API HTTP o la línea de comandos. La aplicación utiliza el modelo fakeprint de [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector), distribuido con licencia MIT, y se ejecuta en una CPU, sin GPU, API de inferencia de pago ni dependencias de entrenamiento.

El pequeño modelo ONNX está incluido. El audio se procesa en el equipo que ejecuta la aplicación y no se envía a un servicio externo de detección.

## Instalación de escritorio

Descarga y descomprime este proyecto y, a continuación, ejecuta el instalador correspondiente a tu equipo:

| Plataforma | Primera instalación |
| --- | --- |
| macOS 13 o posterior, Apple Silicon o Intel | Haz doble clic en `Install.command`. |
| Windows 10/11, x64 | Haz doble clic en `Install.cmd`. |

El instalador prepara una instalación privada de Python, FFmpeg/ffprobe y las dependencias de la aplicación, crea accesos de inicio y parada en el escritorio y abre la aplicación. En Windows también prepara un entorno de ejecución privado de Microsoft Visual C++ para ONNX Runtime. Usa `--no-launch` para instalar sin abrir el navegador. No requiere una instalación previa de Python, Git, Homebrew ni permisos de administrador, y no modifica el PATH global. La primera instalación requiere conexión a Internet. Las descargas de uv, FFmpeg y el entorno de ejecución de C++ para Windows utilizan versiones fijas y se verifican mediante sumas de comprobación; consulta las [dependencias del instalador](install/README.md).

Después de instalar, haz doble clic en el acceso **AI Song Detection** del escritorio. El lanzador inicia el servicio local, espera a que el modelo y el decodificador estén listos y abre el navegador predeterminado. Selecciona o arrastra varios archivos de audio y pulsa **Start queue**. Los archivos se procesan de uno en uno; cada elemento muestra el progreso de la carga, la fase de procesamiento y el estado de cancelación. Antes de añadir archivos, elige un punto de inicio y un intervalo de 10–300 segundos. Puedes volver a consultar los resultados de la sesión, copiarlos o descargarlos en JSON/CSV. Los inicios posteriores y la detección funcionan sin conexión. La copia instalada es independiente de la carpeta del código fuente descomprimido.

Los clics repetidos vuelven a abrir la instancia existente. Si otra aplicación ocupa el puerto preferido, el lanzador elige uno disponible. Cerrar el navegador no detiene el detector; cuando termines, usa el acceso **Stop AI Song Detection** del escritorio o el comando `stop`.

macOS o Windows pueden mostrar una advertencia de origen o seguridad para los scripts descargados que no estén firmados. El instalador no desactiva Gatekeeper, SmartScreen ni las políticas de seguridad de la empresa. Estos instaladores mediante scripts no son paquetes de aplicación firmados para usuarios finales.

Consulta [Operaciones](docs/operations.md) para conocer las rutas de instalación, el inicio desde la línea de comandos, los registros y la resolución de problemas. Las pruebas de verificación por plataforma se documentan por separado en [Verificación](docs/verification.md).

### Línea de comandos

El instalador muestra la ruta de su script de acceso a los comandos. Por ejemplo, puedes iniciar la copia instalada con:

```bash
# macOS
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" launch
```

```powershell
# Windows PowerShell
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" launch
```

El mismo script acepta comandos de detección, diagnóstico, mantenimiento y creación de paquetes de instalación sin conexión. Desde una copia del repositorio para desarrollo, usa:

```bash
uv run ai-song-detection launch
uv run ai-song-detection status
uv run ai-song-detection stop
uv run ai-song-detection detect song.mp3
uv run ai-song-detection detect song.mp3 another-song.flac --json
uv run ai-song-detection detect ./songs --recursive --start 30 --duration 60 --output reports.csv
uv run ai-song-detection doctor --json
uv run ai-song-detection logs --lines 100
uv run ai-song-detection status --url
uv run ai-song-detection launch --port 8001 --strict-port
uv run ai-song-detection evaluate labeled-songs.csv --output evaluation.json
```

`launch` gestiona una instancia en segundo plano y abre el navegador predeterminado. `serve` sigue disponible para ejecutarla en primer plano y detenerla con Ctrl+C. La opción `--no-browser` del lanzador resulta útil para las comprobaciones automatizadas. El modo JSON de detección escribe un objeto JSON por archivo de entrada y termina con el código de salida 1 si falla algún archivo.

En una copia de escritorio instalada, `update` prepara y comprueba una nueva versión antes de cambiar a ella. `cleanup --keep 2` y `uninstall` muestran una vista previa de sus cambios; añade `--apply` para ejecutarlos. Detén el servicio antes de limpiar versiones antiguas. Usa `shell-setup --directory "$HOME/.local/bin"` para crear un comando corto en el directorio que elijas; si es necesario, añade ese directorio al PATH de tu shell. Consulta [mantenimiento e instalación sin conexión](docs/operations.md#maintenance-and-offline-installation).

### API HTTP

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
curl http://127.0.0.1:8000/health
```

Usa la dirección que muestre `launch` o `status`; sustituye el puerto `8000` de estos ejemplos si se ha seleccionado otro. La documentación interactiva de la API está disponible en `/docs` en esa dirección. Consulta [Operaciones](docs/operations.md) para conocer los campos de respuesta, los límites y los errores.

### Docker

```bash
docker compose up --build
```

Abre [http://127.0.0.1:8000](http://127.0.0.1:8000). La imagen incluye Python, FFmpeg, las dependencias y el modelo. Compose vincula el puerto del host a localhost y ejecuta un contenedor sin privilegios de root, con un sistema de archivos raíz de solo lectura y almacenamiento temporal. La compilación de la imagen requiere acceso a la red; la inferencia no.

## Resultados y límites

- `likely_ai_generated`: puntuación de IA superior a 0.6.
- `likely_human_created`: puntuación de IA inferior a 0.4.
- `uncertain`: puntuación de IA entre 0.4 y 0.6, ambos incluidos.

La puntuación de IA es la salida del modelo que utiliza la política de decisión anterior. Los informes incluyen la puntuación, la evaluación, el intervalo analizado y los detalles del modelo.

La interfaz web admite una cola de varios archivos; cada carga a la API acepta un archivo de hasta **100 MiB**, con al menos **10 segundos** de audio. Las extensiones admitidas son MP3, WAV, FLAC, M4A, AAC, OGG, Opus, AIFF/AIF y WMA, según la compatibilidad del decodificador. El audio debe ser mono o estéreo y tener una frecuencia de muestreo de 16–96 kHz. El análisis utiliza por defecto los **primeros 300 segundos**, con la opción de indicar un punto de inicio y una duración de 10–300 segundos. Los informes indican el intervalo realmente analizado y si se omitió parte del audio. Solo se ejecuta un análisis a la vez. La API de trabajos admite hasta nueve trabajos pendientes: uno en ejecución y ocho en espera o en proceso de carga; el endpoint síncrono devuelve 429 mientras está ocupado.

El modelo está orientado a los artefactos de **Suno ≤ 5 y Udio ≤ 1.5**. La detección evalúa características del audio; la autoría, la titularidad de los derechos de autor y el historial de producción requieren sus propios registros de respaldo.

## Referencia del modelo y coste de ejecución

El proyecto original [informa de una exactitud del 99.88 %](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance) en su conjunto reservado para pruebas de 17.866 muestras.

La inferencia local en CPU evita las tarifas por solicitud de los servicios de detección. La latencia y el coste real dependen del hardware, la duración de las canciones, la concurrencia y el alojamiento. Consulta el [Plan de evaluación](docs/evaluation.md) para la evaluación con conjuntos de datos y la medición del rendimiento.

## Desarrollo

El desarrollo requiere Python 3.11–3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/) y FFmpeg/ffprobe en el PATH. El instalador de escritorio prepara su propio entorno.

```bash
uv sync --frozen
uv run ai-song-detection launch
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

En macOS/Linux, `./start.sh` inicia un entorno de desarrollo ya creado sin sincronizar ni descargar dependencias. Usa `uv run ai-song-detection serve --port 8001` para ejecutar un servicio en primer plano en el puerto elegido.

El inglés es el idioma principal del proyecto; se proporcionan traducciones del README como referencia. No incluyas credenciales ni audio privado en Git. El modelo incluido, con su atribución, es la excepción deliberada a la regla general de no incorporar archivos de modelos al repositorio.

## Documentación y licencia

- [Alcance del producto](docs/product-scope.md)
- [Operaciones y contrato de la API](docs/operations.md)
- [Plan de evaluación](docs/evaluation.md)
- [Registro de verificación](docs/verification.md)
- [Avisos de terceros](THIRD_PARTY_NOTICES.md)

El código original del proyecto se distribuye con licencia [Apache 2.0](LICENSE). El modelo del proyecto original y el método de inferencia adaptado conservan su [aviso MIT](third_party/ai-music-detector/LICENSE). La procedencia del modelo, la revisión fija del proyecto original y la suma de comprobación se incluyen entre los recursos del paquete. Las demás dependencias conservan sus respectivas licencias.
