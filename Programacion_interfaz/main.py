"""
main.py
Servidor FastAPI para el monitor del robot agrícola.
Usa Server-Sent Events (SSE) para enviar datos al navegador
en tiempo real sin necesidad de WebSockets.

Acceder desde la red local:
  http://<IP-de-la-raspberry>:8000
"""

# Framework principal para construir la API web
from fastapi import FastAPI

# HTMLResponse: para devolver páginas HTML directamente
# StreamingResponse: para enviar datos en tiempo real (SSE)
from fastapi.responses import HTMLResponse, StreamingResponse

# Permite servir archivos estáticos
from fastapi.staticfiles import StaticFiles

# Módulo propio que maneja la lectura del puerto serial
from serial_reader import SerialReader

# Para operaciones asíncronas (necesario para SSE sin bloquear el servidor)
import asyncio

# Cola thread-safe para pasar datos del hilo serial al hilo de la API
import queue

# Para registrar timestamps en las lecturas del sensor
import datetime

# Para serializar/deserializar datos al formato JSON (envío al frontend)
import json

app = FastAPI()

# Sirve los archivos estáticos (HTML) desde la carpeta /static
app.mount("/static", StaticFiles(directory="static"), name="static")


# Estado global del robot

# Diccionario central con toda la info del robot.
# Se actualiza cada vez que llega un mensaje del Arduino y
# se consulta cuando se carga la pagina.
estado = {
    "cuadrantes": {str(i): "?" for i in range(1, 37)},  # 36 cuadrantes; "?" = sin datos aún
    "robot": "DESCONECTADO",   # Estado actual: CSTART, CPAUSE, CSTOP, CFIN o DESCONECTADO
    "log": []                  # Historial de eventos (máx. 100 líneas)
}

# Lista de colas — una por cada navegador conectado al stream SSE.
# Cuando llega un evento del Arduino, se mete en TODAS las colas
clientes: list[asyncio.Queue] = []


# Helpers 

def agregar_log(mensaje):
    """
    Agrega una entrada al historial con marca de tiempo.
    Si ya hay 100 líneas, elimina la más antigua para no crecer infinito.
    Devuelve la línea formateada (útil para incluirla en el broadcast).
    """
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    entrada = f"[{hora}] {mensaje}"
    estado["log"].append(entrada)
    if len(estado["log"]) > 100:
        estado["log"].pop(0)   # Elimina la línea más antigua
    return entrada


def broadcast(evento: dict):
    """
    Manda un evento a todos los navegadores conectados via SSE.
    Usa put_nowait (no bloquea) para no frenar el hilo principal.
    Si la cola de algún cliente está llena, simplemente se ignora
    ese evento para ese cliente (no lanzamos excepción).
    """
  
    for q in clientes:
        try:
            q.put_nowait(evento)
        except asyncio.QueueFull:
            pass  # Cliente lento: perdió este evento, no pasa nada


# Callbacks del SerialReader
# Estas funciones se llaman automáticamente desde serial_reader.py
# cada vez que llega un mensaje del Arduino.

def on_cuadrante(numero, estado_cuad):
    """
    Se activa cuando el Arduino reporta el estado de un cuadrante.
    Actualiza el diccionario global, genera una línea de log
    y notifica a todos los clientes conectados.
    """
    estado["cuadrantes"][str(numero)] = estado_cuad
    nombre = "HÚMEDO" if estado_cuad == "H" else "SECO"
    log = agregar_log(f"C{numero:02d} → {nombre}")
    broadcast({"tipo": "cuadrante", "num": numero, "estado": estado_cuad, "log": log})


def on_estado_robot(mensaje):
    """
    Se activa cuando el Arduino manda un comando de control
    (CSTART, CPAUSE, CSTOP, CFIN).
    Actualiza el estado global y notifica a los clientes.
    """
    estado["robot"] = mensaje
    log = agregar_log(f"Robot: {mensaje}")
    broadcast({"tipo": "estado", "robot": mensaje, "log": log})


# Inicialización del SerialReader 
# Se crea el objeto aquí (a nivel de módulo) para que viva durante
# todo el ciclo de vida de la aplicación.

serial_reader = SerialReader(
    callback_cuadrante = on_cuadrante,
    callback_estado    = on_estado_robot
)


# Eventos de ciclo de vida de FastAPI 

@app.on_event("startup")
async def startup():
    """
    Se ejecuta automáticamente cuando FastAPI arranca.
    Abre el puerto serial para empezar a recibir datos del Arduino.
    """
    ok = serial_reader.iniciar()
    if ok:
        agregar_log("Puerto serial abierto ✓")
    else:
        agregar_log("ERROR: No se pudo abrir el puerto serial")


@app.on_event("shutdown")
async def shutdown():
    """
    Se ejecuta automáticamente cuando FastAPI se apaga.
    Cierra el puerto serial limpiamente para no dejarlo ocupado.
    """
    serial_reader.detener()


# Rutas HTTP

@app.get("/", response_class=HTMLResponse)
async def index():
    """
    Ruta principal — sirve el dashboard HTML.
    Lee el archivo directamente del disco cada vez que alguien entra.
    """
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/estado")
async def get_estado():
    """
    Devuelve el estado completo del robot como JSON.
    El navegador llama a esto UNA VEZ al cargar la página para
    mostrar los datos actuales antes de que lleguen eventos nuevos.
    """
    return estado


from starlette.requests import Request

@app.get("/eventos")
async def eventos(request: Request):
    """
    Endpoint SSE (Server-Sent Events).
    Cuando el navegador se conecta aquí, el servidor mantiene
    la conexión abierta y va enviando eventos en tiempo real
    conforme llegan del Arduino, sin que el cliente tenga que
    hacer polling (preguntar repetidamente).

    Flujo:
      1. Se crea una cola exclusiva para este cliente.
      2. Se agrega a la lista global de clientes.
      3. Se entra al bucle: espera eventos en la cola y los
         envía al navegador en formato SSE ("data: {...}\n\n").
      4. Si pasa 1 segundo sin eventos, manda un "ping" para
         mantener la conexión viva (evita timeouts del navegador).
      5. Cuando el cliente se desconecta, su cola se elimina
         de la lista global (bloque finally).
    """
    q = asyncio.Queue(maxsize=50)
    clientes.append(q)

    async def generador():
        try:
            while True:
                # Si el navegador cerró la pestaña o perdió conexión, salimos
                if await request.is_disconnected():
                    break
                try:
                    # Espera un evento nuevo en la cola (máximo 1 segundo)
                    evento = await asyncio.wait_for(q.get(), timeout=1.0)
                    # Formato SSE estándar: "data: <json>\n\n"
                    yield f"data: {json.dumps(evento)}\n\n"
                except asyncio.TimeoutError:
                    # No hubo eventos en 1 seg → mandamos un comentario vacío
                    # para que el navegador sepa que la conexión sigue viva
                    yield ": ping\n\n"
        finally:
            # Pase lo que pase (error, desconexión), limpiamos la cola de la lista
            clientes.remove(q)

    return StreamingResponse(
        generador(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",       # No guardar en caché — es un stream en vivo
            "X-Accel-Buffering": "no"          # Le dice a Nginx que no acumule el stream
        }
    )


@app.post("/comando/{cmd}")
async def comando(cmd: str):
    """
    Recibe comandos desde los botones del dashboard web y los
    reenvía al Arduino por el puerto serial.

    Comandos válidos:
      R → RUN   (iniciar movimiento)
      P → PAUSE (pausar)
      S → STOP  (detener)

    Si el comando no es ninguno de esos tres, devuelve error.
    """
    if cmd in ("R", "P", "S"):
        serial_reader.enviar(cmd)          # Lo manda al Arduino
        nombres = {"R": "RUN", "P": "PAUSE", "S": "STOP"}
        log = agregar_log(f"Enviado: {nombres[cmd]}")
        broadcast({"tipo": "log", "log": log})   # Notifica a todos los clientes
        return {"ok": True}
    return {"ok": False, "error": "Comando inválido"}
