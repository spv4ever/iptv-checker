# Comprobador de URLs

Aplicación gráfica sencilla, escrita en Python, para comprobar varias URLs a la
vez. No necesita instalar paquetes adicionales.

## Iniciar en Windows

Abre una terminal en esta carpeta y ejecuta:

```bat
python app.py
```

También puedes abrir `iniciar.bat` con doble clic.

Pega una URL Xtream `http://` o `https://` por línea y pulsa **Guardar
pendientes**. Esta primera fase sólo valida el formato y guarda las cuentas, sin
conectarse a ningún servidor. El campo **Cuentas por lote** permite elegir
cuántas se procesarán al pulsar **Validar siguiente lote**. Las cuentas se toman
de una única cola, en el mismo orden en que se guardaron, sin agruparlas por
servidor.

Requiere Python 3.10 o posterior. La interfaz utiliza Tkinter, incluido en la
instalación normal de Python para Windows.

## Base de datos Xtream Codes

El paquete incluye una base SQLite para guardar los datos de acceso ya
segmentados: nombre del servidor, URL base normalizada, usuario, contraseña,
estado de validez (incluido **Pendiente sin validar**), fecha de la última
validación y fecha de caducidad. Cada combinación exacta de servidor, usuario y
contraseña tiene un GUID determinista: volver a pegar la misma información no
crea otra alta ni devuelve una cuenta ya validada al estado pendiente.

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
queda guardada primero como pendiente. La validación posterior se realiza en
lotes globales del tamaño elegido y siguiendo el orden de guardado. Las URLs
genéricas que no contienen usuario y contraseña se ignoran porque no permiten crear una
cuenta Xtream. La contraseña no se muestra en esta vista.

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
Al seleccionar una cuenta, el botón **Ver detalles** abre todos sus datos,
incluidos la contraseña y el enlace M3U completo. Cada campo se puede copiar por
separado para pegarlo en un reproductor o software de streaming; **Copiar todos**
los reúne en el portapapeles en un solo paso. Las credenciales sólo se revelan
en esta ventana de detalle y no en la tabla general.
Si la fecha ya ha vencido o la API no responde al abrir la cuenta, ésta queda
marcada en rojo como **Obsoleta**. El botón **Limpiar cuentas obsoletas** permite
borrar de SQLite, previa confirmación, las cuentas caducadas o fallidas del
servidor seleccionado.

Haz doble clic en cualquier canal para abrirlo directamente en la ventana nativa
del primer reproductor disponible: **mpv**, **ffplay** o **VLC**. No se crea una
ventana emergente propia ni se intenta incrustar la imagen en la aplicación; el
reproductor gestiona el tamaño, la relación de aspecto y sus controles. La URL
directa generada por Xtream ya contiene el usuario y la contraseña necesarios.
Añade al menos uno de esos reproductores al `PATH` (VLC también se busca en sus
ubicaciones de instalación habituales en Windows y macOS).

## Pruebas

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
