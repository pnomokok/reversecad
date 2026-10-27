"""Ortam kontrolu: paketler yuklu mu, .env'deki anahtarlar dolu mu?

Anahtarlarin degerini asla yazdirmaz; yalnizca "dolu" / "BOS" der.
Calistirma: .venv\\Scripts\\python.exe check_env.py
"""
import importlib
import os

from dotenv import load_dotenv

# (ice aktarma adi, ekranda gorunecek ad)
PACKAGES = [
    ("cadquery", "cadquery"),
    ("cv2", "opencv-python"),
    ("numpy", "numpy"),
    ("dotenv", "python-dotenv"),
    ("requests", "requests"),
    ("pytest", "pytest"),
]

KEYS = ["BASETEN_API_KEY", "META_API_KEY"]


def main():
    print("Paketler:")
    for module_name, label in PACKAGES:
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "?")
            print(f"  OK   {label} {version}")
        except ImportError as error:
            print(f"  HATA {label}: {error}")

    load_dotenv()
    print("Anahtarlar (.env):")
    for key in KEYS:
        status = "dolu" if os.getenv(key) else "BOS"
        print(f"  {key}: {status}")


if __name__ == "__main__":
    main()
