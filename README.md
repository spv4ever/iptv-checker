# IPTV Checker

Comprobador de listas IPTV escrito en Python y sin dependencias externas. Lee una
lista M3U, comprueba sus URLs HTTP(S) en paralelo y muestra un resumen legible o
JSON para integrarlo con otros procesos.

## Uso

```bash
python -m iptv_checker lista.m3u
python -m iptv_checker lista.m3u --workers 20 --timeout 5 --json
```

También se puede instalar como comando:

```bash
python -m pip install .
iptv-checker lista.m3u
```

El código de salida es `0` cuando todos los canales responden correctamente y
`1` cuando alguno falla. Las entradas sin URL o con un esquema no soportado se
descartan con un aviso durante el parseo.

## Desarrollo

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
