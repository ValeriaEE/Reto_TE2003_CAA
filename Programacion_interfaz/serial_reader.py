"""
serial_reader.py
Lector UART en hilo separado.
Arduino Uno → /dev/ttyUSB0 o /dev/ttyACM0 a 9600 baudios
"""
import serial
import serial.tools.list_ports
import threading

# Velocidad de comunicación con el Arduino (bits por segundo).
BAUDIOS = 9600


def detectar_puerto():
    """
    Busca automáticamente en qué puerto USB está conectado el Arduino.
    Primero revisa los nombres de los puertos disponibles buscando palabras
    clave típicas. Si no encuentra nada así, intenta abrir
    los puertos más comunes uno por uno hasta que alguno funcione.
    Devuelve la ruta del puerto (ej. '/dev/ttyUSB0') o None si no encontró nada.
    """
    # Paso 1: escanear todos los puertos serie del sistema
    for puerto in serial.tools.list_ports.comports():
        if any(x in puerto.description for x in ("Arduino", "CH340", "ttyUSB", "ttyACM")):
            print(f"[SerialReader] Arduino detectado en {puerto.device}")
            return puerto.device  # si se encuentra Devolvemos su ruta

    # Paso 2: si el escaneo no funcionó, intentar abrir los puertos más comunes
    # en Linux a la fuerza 
    for candidato in ("/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1", "/dev/ttyACM1"):
        try:
            s = serial.Serial(candidato, BAUDIOS, timeout=1)
            s.close()  # Solo queríamos verificar que abre sin error; lo cerramos
            print(f"[SerialReader] Puerto encontrado: {candidato}")
            return candidato
        except serial.SerialException:
            continue  # Este puerto no funcionó, probamos el siguiente

    return None  # No encontramos ningún Arduino 


class SerialReader:
    """
    Maneja toda la comunicación serie con el Arduino.

    Funciona así:
      1. Se conecta al puerto donde está el Arduino.
      2. Lanza un hilo en segundo plano que lee mensajes continuamente.
      3. Cada mensaje recibido se analiza y se pasa a una función callback
         según su tipo (comando de estado o número de cuadrante).

    Los callbacks son funciones que se definen fuera de esta clase y que
    se llaman automáticamente cuando llega un mensaje
    """

    def __init__(self, callback_cuadrante, callback_estado):
        """
        callback_cuadrante: función que se llama cuando el Arduino reporta
                            qué cuadrante se activó (ej. cuadrante 12, tipo 'H').
        callback_estado:    función que se llama cuando el Arduino manda un
                            comando de control (CSTART, CPAUSE, CSTOP, CFIN).
        """
        self.callback_cuadrante = callback_cuadrante
        self.callback_estado    = callback_estado
        self.ser    = None   # Aquí vivirá la conexión serie una vez abierta
        self.activo = False  # Bandera para saber si el hilo lector debe seguir corriendo

    def iniciar(self):
        """
        Abre la conexión con el Arduino y arranca el hilo lector en segundo plano.
        Devuelve True si todo salió bien, False si no encontró el Arduino o hubo error.
        """
        puerto = detectar_puerto()
        if not puerto:
            print("[SerialReader] No se encontró ningún Arduino conectado")
            return False

        try:
            self.ser    = serial.Serial(puerto, BAUDIOS, timeout=1)
            self.activo = True
            # daemon=True significa que el hilo muere automáticamente si
            # el programa principal termina (no hay que cerrarlo manualmente)
            threading.Thread(target=self._leer, daemon=True).start()
            return True
        except serial.SerialException as e:
            print(f"[SerialReader] Error: {e}")
            return False

    def _leer(self):
        """
        Bucle infinito que corre en el hilo secundario.
        Lee una línea del puerto serie, la limpia y la manda a parsear
        Se detiene cuando self.activo se vuelve False.
        """
        while self.activo:
            try:
                # readline() bloquea hasta recibir '\n' o que venza el timeout (1 seg)
                linea = self.ser.readline().decode("ascii").strip()
                if not linea:
                    continue  # Línea vacía (timeout), volvemos a esperar
                self._parsear(linea)
            except Exception as e:
                print(f"[SerialReader] Error leyendo: {e}")

    def _parsear(self, linea):
        """
        Interpreta el mensaje recibido del Arduino y llama al callback correcto.

        Hay dos tipos de mensajes válidos:

        1. Comandos de estado — exactamente una de estas palabras:
              CSTART  →  empieza el juego/proceso
              CPAUSE  →  pausa
              CSTOP   →  detiene
              CFIN    →  terminó

        2. Mensajes de cuadrante — formato: C<NN><T>
              C  = letra fija que indica "cuadrante"
              NN = número de 2 dígitos entre 01 y 36 (ej. "07", "24")
              T  = tipo: 'H' (hit/golpe) o 'S' (suelto/liberado)
              Ejemplo: "C07H" → cuadrante 7 fue golpeado
                       "C24S" → cuadrante 24 fue soltado

        Si el mensaje no encaja en ninguno de los dos formatos, se imprime
        como desconocido.
        """
        # ¿Es un comando de estado conocido?
        if linea in ("CSTART", "CPAUSE", "CSTOP", "CFIN"):
            self.callback_estado(linea)
            return

        # ¿Tiene la forma C<NN><T>? (4 caracteres, empieza con 'C', NN es numérico,
        # última letra es 'H' o 'S')
        if (len(linea) == 4 and linea[0] == 'C'
                and linea[1:3].isdigit()
                and linea[3] in ('H', 'S')):
            numero = int(linea[1:3])
            if 1 <= numero <= 36:  # Solo aceptamos cuadrantes del 1 al 36
                self.callback_cuadrante(numero, linea[3])
                return

        # Si llegamos aquí, el mensaje no encajó en ningún formato esperado
        print(f"[SerialReader] Desconocido: '{linea}'")

    def enviar(self, cmd):
        """
        Envía un comando al Arduino (de Python → Arduino).
        Solo intenta enviar si el puerto está abierto.
        """
        if self.ser and self.ser.is_open:
            self.ser.write(cmd.encode("ascii"))

    def detener(self):
        """
        Para el hilo lector y cierra la conexión serie.
        Llamar esto antes de cerrar el programa para no dejar el puerto ocupado.
        """
        self.activo = False  # El hilo lector verá esto en su próxima iteración y saldrá
        if self.ser:
            self.ser.close()
