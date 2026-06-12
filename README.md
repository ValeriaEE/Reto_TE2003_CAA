# Reto_TE2003_CAA
Reto final de la clase Diseño de sistemas de chip 



**robot_arduino.ino** es el programa que corre directamente en el Arduino y controla todo el hardware del robot. Se encarga de mover los motores hacia adelante o girar para hacer las vueltas en U entre filas, bajar y subir el servo que lleva el sensor de humedad, leer el valor del suelo y decidir si está seco o húmedo comparándolo contra un umbral. Recorre los 36 cuadrantes en orden y al terminar cada uno manda el resultado por USB como un mensaje de texto simple, por ejemplo `C07H` para "cuadrante 7, húmedo". También escucha comandos que llegan desde la Raspberry Pi (`R`, `P`, `S`) para pausar, reanudar o detener el recorrido en cualquier momento.

**serial_reader.py** corre en la Raspberry Pi y su único trabajo es estar escuchando el puerto USB donde está conectado el Arduino. Lo hace en un hilo separado para no bloquear el resto del programa mientras espera mensajes. Cada vez que llega una línea, la interpreta: si es algo como `C12S` llama a una función avisando que el cuadrante 12 está seco, y si es `CPAUSE` o `CSTOP` llama a otra función avisando del cambio de estado del robot. También puede mandar comandos de regreso al Arduino cuando el usuario presiona un botón en el dashboard.

**main.py** es el servidor web que también corre en la Raspberry Pi. Usa FastAPI para exponer un dashboard accesible desde cualquier navegador en la red local. Lo más interesante es cómo entrega los datos en tiempo real: cuando un navegador abre la página, el servidor mantiene la conexión viva y va mandando cada evento nuevo conforme llega del Arduino, sin que el navegador tenga que estar preguntando constantemente. Si hay varias pestañas abiertas al mismo tiempo, todas reciben los mismos eventos en paralelo. También tiene una ruta para recibir los comandos de los botones del dashboard y reenviarlos al Arduino.

## Protocolo serial (Arduino ↔ Raspberry Pi)
 
El Arduino manda mensajes de texto simples por USB:
 
| Mensaje | Significado |
|---|---|
| `CSTART` | Listo, esperando inicio |
| `C07H` | Cuadrante 7 → húmedo |
| `C07S` | Cuadrante 7 → seco |
| `CPAUSE` | Robot pausado |
| `CSTOP` | Robot detenido |
| `CFIN` | Mapeo completo |
 
La Raspberry Pi puede mandar: `R` (run), `P` (pause), `S` (stop)
 
## Correr el servidor
 
```bash
pip install fastapi uvicorn pyserial
uvicorn main:app --host 0.0.0.0 --port 8000
```
 
Luego abrir `http://<IP-de-la-raspberry>:8000` en el navegador.
