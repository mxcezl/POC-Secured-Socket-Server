import os
import sys
import time
import socket
import signal
import asyncio
import numpy as np
from multiprocessing import shared_memory

""" Definition des constantes """
pathtube1 = "/tmp/tube_P-S.fifo"
pathtube2 = "/tmp/tube_S-P.fifo"
values_shm_ini = np.array([1, 0, 1, 0, 0, 1])

HOST = '127.0.0.1'
PORT_SERVER_CLIENT = 3333
PORT_WATCHDOG_PRINCIPAL = 1111
PORT_WATCHDOG_SECONDAIRE = 2222

SLEEP_TIME = 0.5

def creation_tubes():
    """ Creation des tubes de facon securisee """
    try:
        os.mkfifo(pathtube1, 0o0600)
    except OSError:
        print("Tube principal non cree car il existe deja.")

    try:
        os.mkfifo(pathtube2, 0o0600)
    except OSError:
        print("Tube secondaire non cree car il existe deja.")

# Pour la fermeture controlee avec Ctrl+C
def signal_handler_exit(sig, frame):
    print('\nArret du script, vous avez Ctrl+C!')

    supprimer_tubes()

    # Fermeture du segment memoire partage
    shm.close()
    shm.unlink()

    os._exit(0)

def supprimer_tubes():
    # Fermeture des tubes nommes
    if os.path.exists(pathtube1):
        os.unlink(pathtube1)
    if os.path.exists(pathtube2):
        os.unlink(pathtube2)

def processus_watchdog_traitement():
    return 0

async def handle_client(reader,writer):
    request = None
    print("1")
    while request != 'quit':
        request = (reader.read(255)).decode('utf8')
        print("2")
        print('recu : ' + str(request))
        response = str('OK ' + request) + '\n'
        writer.write(response.encode('utf8'))
        await writer.drain()
    writer.close()

async def run_server_socket():
    print("RUn serv")
    server = await asyncio.start_server(handle_client, HOST, PORT_SERVER_CLIENT)
    print('runned')
    async with server:
        await server.serve_forever()


def processus_pere_traitement():
    signal.signal(signal.SIGINT, signal_handler_exit)
    shm_parent = shared_memory.SharedMemory(name=shm.name)

    pid_watchdog = -1
    try:
        pid_watchdog = os.fork()
        if pid_watchdog < 0:
            print("Erreur lors du fork()")
            os.abort()
    except OSError as e:
        print("Creation du processus fils impossible, arret du script.\n" + str(e))
        os.abort()
    
    if pid_watchdog == 0: # Fils
        processus_watchdog_traitement()
        os.abort()
    elif pid_watchdog > 1: # Pere

        print("TEst")
        asyncio.run(run_server_socket())
        print("LOl")
        i = 0
        while True:
            try:
                fifo1 = open(pathtube1, "w")
                fifo2 = open(pathtube2, "r")
            except Exception as e:
                print("Erreur lors de l'ouverture des tubes, arret du script.\n" + str(e))
                os._exit(1)
            
            fifo1.write("Message " + str(i) + " du processus principal !\n")
            fifo1.flush()

            print("Message recu : " + fifo2.readline())

            fifo2.flush()

            i += 1
            time.sleep(SLEEP_TIME)


        # Le processus pere est le premier a se terminer
        shm_parent.close()
        shm_parent.unlink()

def processus_fils_traitement():
    try:
        shm_fils = shared_memory.SharedMemory(name=shm.name)
        i = 0
        while True:
            try:
                fifo1 = open(pathtube1, "r")
                fifo2 = open(pathtube2, "w")
            except Exception as e:
                print("Erreur lors de l'ouverture des tubes, arret du script.\n" + str(e))
                os._exit(1)

            print("Message recu : " + fifo1.readline())

            fifo1.flush()

            fifo2.write("Message " + str(i) + " du processus secondaire !\n")
            fifo2.flush()

            i += 1
            
        print ("Le père boucle...")
        shm_fils.close()
    except KeyboardInterrupt:
        os.abort()



try:
    os.unlink('/dev/shm/segment_mm')
except Exception:
    pass

# Creation du segment memoire
shm = shared_memory.SharedMemory(create=True, size=values_shm_ini.nbytes, name="segment_mm")
b = np.ndarray(values_shm_ini.shape, dtype=values_shm_ini.dtype, buffer=shm.buf)
b[:] = values_shm_ini[:]

creation_tubes()

pid = -1
try:
    pid = os.fork()
    if pid < 0:
        print("Erreur lors du fork()")
        os.abort()
except OSError as e:
    print("Creation du processus fils impossible, arret du script.\n" + str(e))
    os.abort()

# Parent
if pid > 0:
    processus_pere_traitement()
    os.abort()
elif pid == 0: # Fils
    processus_fils_traitement()
    os.abort()
else:
    os.abort()

supprimer_tubes()