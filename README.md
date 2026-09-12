# Comprobador de URLs

Aplicación gráfica sencilla, escrita en Python, para comprobar varias URLs a la
vez. No necesita instalar paquetes adicionales.

## Iniciar en Windows

Abre una terminal en esta carpeta y ejecuta:

```bat
python app.py
```

También puedes abrir `iniciar.bat` con doble clic.

Pega una URL `http://` o `https://` por línea y pulsa **Comprobar**. La tabla
mostrará si cada dirección está disponible, su código HTTP y el tiempo de
respuesta.

Requiere Python 3.10 o posterior. La interfaz utiliza Tkinter, incluido en la
instalación normal de Python para Windows.

## Base de datos Xtream Codes

El paquete incluye una base SQLite para guardar los datos de acceso ya
segmentados: nombre del servidor, URL base normalizada, usuario, contraseña,
estado de validez, fecha de la última validación y fecha de caducidad. Las
altas son idempotentes por URL y usuario.

```python
from iptv_checker import XtreamDatabase, parse_xtream_url

cuenta = parse_xtream_url(
    "http://tv.example:8080/get.php?username=usuario&password=clave&type=m3u_plus",
    server_name="Servidor de casa",
)
XtreamDatabase("xtream.db").save(cuenta)
```

También se admiten enlaces directos con el formato
`/live/usuario/contraseña/canal.ts`. La URL normalizada nunca contiene las
credenciales. La contraseña sí se conserva en SQLite porque es necesaria para
configurar Xtream Codes; el archivo se crea con permisos `0600` en sistemas
POSIX y no debe compartirse ni añadirse al control de versiones.

Desde la aplicación gráfica también puedes pulsar **Base de datos guardados**
para consultar las cuentas almacenadas, su estado y sus fechas de validación y
caducidad. Cada URL Xtream que termina la comprobación con resultado disponible
se guarda automáticamente como válida, junto con la fecha de validación. Las
URLs genéricas que no contienen usuario y contraseña sólo se comprueban. La
contraseña no se muestra en esta vista.

Haz doble clic en una cuenta de la ventana de la base de datos para consultar
su estado actual y obtener desde `player_api.php` la lista de canales live. La
aplicación **descarga y muestra la lista completa sin iniciar la comprobación**.
Puedes filtrar la tabla por nombre y categoría y pulsar **Iniciar comprobación**
cuando hayas preparado la selección: sólo se revisan los canales visibles en ese
momento. **Parar comprobación** permite detener el proceso. Durante la revisión,
la tabla conserva únicamente los canales «Pendiente» y «Accesible»: los que
resultan no accesibles desaparecen automáticamente. Los resultados se procesan
por lotes y las pruebas de red se ejecutan en paralelo para mantener ágil la
interfaz incluso con listas grandes.
Al consultar los canales también se actualizan en SQLite el estado, la fecha de
validación y la caducidad devuelta por la cuenta Xtream. El panel **Actividad** y
el estado de la ventana de canales indican qué fase se está ejecutando.

Haz doble clic en cualquier canal para abrir una ventana de reproducción
integrada. La aplicación inicia automáticamente **mpv** y, si no está disponible
o no puede arrancar, prueba **ffplay**. Incluye controles para reproducir,
pausar/continuar, parar, ajustar el volumen y cerrar. La URL directa generada por
Xtream ya contiene el usuario y la contraseña necesarios. Añade `mpv` o `ffplay`
al `PATH`; en algunos entornos
Wayland, la integración de ffplay depende de la compatibilidad XWayland/SDL del
sistema, mientras que mpv es la opción recomendada.

## Pruebas

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
