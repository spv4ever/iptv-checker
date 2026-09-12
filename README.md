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

## Pruebas

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
