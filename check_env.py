"""Environment check: are the packages installed and are the .env keys set?

Never prints key values; only reports "set" / "MISSING".
Run: .venv\\Scripts\\python.exe check_env.py
"""
import importlib
import os

from dotenv import load_dotenv

# (import name, display name)
PACKAGES = [
    ("cadquery", "cadquery"),
    ("cv2", "opencv-python"),
    ("numpy", "numpy"),
    ("PIL", "pillow"),
    ("dotenv", "python-dotenv"),
    ("requests", "requests"),
    ("openai", "openai"),
    ("meta_sam_parser", "meta-sam-parser"),
    ("pytest", "pytest"),
]

KEYS = ["BASETEN_API_KEY", "MODEL_API_KEY"]


def main():
    print("Packages:")
    for module_name, label in PACKAGES:
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "?")
            print(f"  OK    {label} {version}")
        except ImportError as error:
            print(f"  ERROR {label}: {error}")

    load_dotenv()
    print("Keys (.env):")
    for key in KEYS:
        status = "set" if os.getenv(key) else "MISSING"
        print(f"  {key}: {status}")


if __name__ == "__main__":
    main()
