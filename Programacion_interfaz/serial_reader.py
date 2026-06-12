"""
serial_reader.py
Lector UART en hilo separado.
Arduino Uno → /dev/ttyUSB0 o /dev/ttyACM0 a 9600 baudios
"""

import serial
import serial.tools.list_ports
import threading

BAUDIOS = 9600


def detectar_puerto():
    """Detecta automáticamente el puerto del Arduino."""
    for puerto in serial.tools.list_ports.comports():
        if any(x in puerto.description for x in ("Arduino", "CH340", "ttyUSB", "ttyACM")):
            print(f"[SerialReader] Arduino detectado en {puerto.device}")
            return puerto.device
    # Fallback: intenta los puertos más comunes
    for candidato in ("/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1", "/dev/ttyACM1"):
        try:
            s = serial.Serial(candidato, BAUDIOS, timeout=1)
            s.close()
            print(f"[SerialReader] Puerto encontrado: {candidato}")
            return candidato
        except serial.SerialException:
            continue
    return None


class SerialReader:

    def __init__(self, callback_cuadrante, callback_estado):
        self.callback_cuadrante = callback_cuadrante
        self.callback_estado    = callback_estado
        self.ser    = None
        self.activo = False

    def iniciar(self):
        puerto = detectar_puerto()
        if not puerto:
            print("[SerialReader] No se encontró ningún Arduino conectado")
            return False
        try:
            self.ser    = serial.Serial(puerto, BAUDIOS, timeout=1)
            self.activo = True
            threading.Thread(target=self._leer, daemon=True).start()
            return True
        except serial.SerialException as e:
            print(f"[SerialReader] Error: {e}")
            return False

    def _leer(self):
        while self.activo:
            try:
                linea = self.ser.readline().decode("ascii").strip()
                if not linea:
                    continue
                self._parsear(linea)
            except Exception as e:
                print(f"[SerialReader] Error leyendo: {e}")

    def _parsear(self, linea):
        if linea in ("CSTART", "CPAUSE", "CSTOP", "CFIN"):
            self.callback_estado(linea)
            return

        if (len(linea) == 4 and linea[0] == 'C'
                and linea[1:3].isdigit()
                and linea[3] in ('H', 'S')):
            numero = int(linea[1:3])
            if 1 <= numero <= 36:
                self.callback_cuadrante(numero, linea[3])
                return

        print(f"[SerialReader] Desconocido: '{linea}'")

    def enviar(self, cmd):
        if self.ser and self.ser.is_open:
            self.ser.write(cmd.encode("ascii"))

    def detener(self):
        self.activo = False
        if self.ser:
            self.ser.close()