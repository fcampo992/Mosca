"""
Vercel entrypoint — importa la app Flask y la expone como WSGI handler.
"""
import sys
import os

# Asegurarse de que el directorio raíz esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archer.app import app  # noqa: E402

# Vercel busca una variable llamada `app` en este módulo
__all__ = ["app"]
