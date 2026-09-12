"""Inicia la interfaz grafica sin necesidad de instalar el proyecto."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parent / "src"))

from iptv_checker.gui import main  # noqa: E402


if __name__ == "__main__":
    main()
