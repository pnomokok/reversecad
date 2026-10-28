"""The online demo on Modal: the web app replaying the saved samples (samples/), with no API keys.

REVERSECAD_DEMO=1 lists only samples/ and turns off everything that needs a key (live mode, repair,
voice editing); downloads, the drawing and the 1:1 template work, since CadQuery runs in the container.
Only code and samples/ go into the image: .env, .venv, outputs/, data/ (private photos) and .git stay home.

Deploy: .venv\\Scripts\\python.exe -m modal deploy modal_app.py      (needs a Modal token: modal token new)
"""
import modal

IGNORE = [".env", ".env.*", ".venv", ".git", "outputs", "data", "design", "**/__pycache__", "**/*.pyc", ".pytest_cache"]

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install_from_requirements("requirements.txt")
    .env({"REVERSECAD_DEMO": "1"})
    .workdir("/root/app")
    .add_local_dir(".", "/root/app", ignore=IGNORE)
)
app = modal.App("reversecad-demo", image=image)


@app.function(cpu=2.0, memory=2048, timeout=600, scaledown_window=300)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import os

    os.chdir("/root/app")  # the app reads samples/ and writes temporary files relative to here
    from webapp.server import app as fastapi_app

    return fastapi_app
