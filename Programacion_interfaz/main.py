"""
main.py
Servidor FastAPI para el monitor del robot agrícola.
Usa Server-Sent Events (SSE) para enviar datos al navegador
en tiempo real sin necesidad de WebSockets.

Acceder desde la red local:
  http://<IP-de-la-raspberry>:8000
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from serial_reader import SerialReader
import asyncio
import queue
import datetime
import json

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Estado global del robot ────────────────────────────────────────
estado = {
    "cuadrantes": {str(i): "?" for i in range(1, 37)},  # ?, H, S
    "robot": "DESCONECTADO",
    "log": []
}

# Cola para enviar eventos SSE a los clientes conectados
clientes: list[asyncio.Queue] = []


def agregar_log(mensaje):
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    entrada = f"[{hora}] {mensaje}"
    estado["log"].append(entrada)
    if len(estado["log"]) > 100:   # máximo 100 líneas
        estado["log"].pop(0)
    return entrada


def broadcast(evento: dict):
    """Envía un evento a todos los clientes SSE conectados."""
    for q in clientes:
        try:
            q.put_nowait(evento)
        except asyncio.QueueFull:
            pass


# ── Callbacks del SerialReader ─────────────────────────────────────

def on_cuadrante(numero, estado_cuad):
    estado["cuadrantes"][str(numero)] = estado_cuad
    nombre = "HÚMEDO" if estado_cuad == "H" else "SECO"
    log = agregar_log(f"C{numero:02d} → {nombre}")
    broadcast({"tipo": "cuadrante", "num": numero, "estado": estado_cuad, "log": log})


def on_estado_robot(mensaje):
    estado["robot"] = mensaje
    log = agregar_log(f"Robot: {mensaje}")
    broadcast({"tipo": "estado", "robot": mensaje, "log": log})


# ── Iniciar SerialReader al arrancar ──────────────────────────────

serial_reader = SerialReader(
    callback_cuadrante = on_cuadrante,
    callback_estado    = on_estado_robot
)

@app.on_event("startup")
async def startup():
    ok = serial_reader.iniciar()
    if ok:
        agregar_log("Puerto serial abierto ✓")
    else:
        agregar_log("ERROR: No se pudo abrir el puerto serial")


@app.on_event("shutdown")
async def shutdown():
    serial_reader.detener()


# ── Rutas ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/estado")
async def get_estado():
    """Estado completo actual — usado al cargar la página."""
    return estado

from starlette.requests import Request

@app.get("/eventos")
async def eventos(request: Request):
    """Server-Sent Events — stream en tiempo real al navegador."""
    q = asyncio.Queue(maxsize=50)
    clientes.append(q)

    async def generador():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evento = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(evento)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            clientes.remove(q)

    return StreamingResponse(
        generador(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/comando/{cmd}")
async def comando(cmd: str):
    """Recibe RUN, PAUSE o STOP desde los botones de la web."""
    if cmd in ("R", "P", "S"):
        serial_reader.enviar(cmd)
        nombres = {"R": "RUN", "P": "PAUSE", "S": "STOP"}
        log = agregar_log(f"Enviado: {nombres[cmd]}")
        broadcast({"tipo": "log", "log": log})
        return {"ok": True}
    return {"ok": False, "error": "Comando inválido"}