#!/usr/bin/env python3
import os
import time
import signal
import asyncio
import numpy as np
from multiprocessing import shared_memory
from threading import Thread

""" Definition des constantes """

# Chemins d'acces
PATHTUBE1 = "/tmp/tube_P-S.fifo"
PATHTUBE2 = "/tmp/tube_S-P.fifo"
PATH_SHM = "/dev/shm/segment_mm"

# Valeurs par defaut du shm
INI_SHM = np.array([1, 0, 1, 0, 0, 1])

# Constantes pour les serveurs Socket
HOST = '127.0.0.1'
PORT_SERVER_CLIENT = 3333
PORT_WATCHDOG_PRINCIPAL = 1111
PORT_WATCHDOG_SECONDAIRE = 2222

# Temps de battement pour la communication par tubes nommes
SLEEP_TIME = 0.5

class EchoClientProtocol(asyncio.Protocol):
    def __init__(self, message, on_con_lost):
        self.message = message
        self.on_con_lost = on_con_lost

    def connection_made(self, transport):
        transport.write(self.message.encode())

    def data_received(self, data):
        print('{!r}'.format(data.decode()))

    def connection_lost(self, exc):
        self.on_con_lost.set_result(True)

# Creation des tubes de facon securisee
def creation_tubes():

    # Tube principal
    try:
        os.mkfifo(PATHTUBE1, 0o0600)
    except OSError:
        print("Tube principal non cree car il existe deja.")

    # Tube secondaire
    try:
        os.mkfifo(PATHTUBE2, 0o0600)
    except OSError:
        print("Tube secondaire non cree car il existe deja.")


# Pour la fermeture controlee avec Ctrl+C
def signal_handler_exit(sig, frame):

    try:
        # Fermeture et suppression des tubes nommes
        supprimer_tubes()
    except Exception:
        pass
    
    # Fermeture du segment memoire partage
    try:
        shm.close()
        shm.unlink()
    except Exception:
        pass
    
    # Clear la console
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Terminer l'execution
    os._exit(0)


# Fermeture et suppression des tubes nommes
def supprimer_tubes():
    
    # On verifie d'abord que le chemin d'acces au tube est valide et que les tubes existent
    if os.path.exists(PATHTUBE1):
        os.unlink(PATHTUBE1)
    if os.path.exists(PATHTUBE2):
        os.unlink(PATHTUBE2)

# Lorsque le WatchDog recoit une reponse de la part du serveur principal
async def handle_watchdog_principal(reader, writer):
    # Reception du message du SP (msg = "SP_OK", en theorie)
    data = await reader.read(100)
    message = data.decode()
    
    msg_retour = "[WD] - WD_CONTROLE_SP_OK" if message == "SP_OK" else "[WD] - WD_CONTROL_SP_DOWN"
    
    # Renvoyer message au SP
    writer.write((msg_retour).encode())
    await writer.drain()
    writer.close()
    
# Lorsque le WatchDog recoit une reponse de la part du serveur secondaire
async def handle_watchdog_secondaire(reader, writer):
    # Reception du message du SS (msg = "SS_OK", en theorie)
    data = await reader.read(100)
    message = data.decode()
    
    msg_retour = "[WD] - WD_CONTROLE_SS_OK" if message == "SS_OK" else "[WD] - WD_CONTROL_SS_DOWN"
    
    # Renvoyer message au SP
    writer.write((msg_retour).encode())
    await writer.drain()
    writer.close()

# Traitement pour le deploiement du watchdog
def processus_watchdog_traitement():

    # demarrage serveur 1 (communication avec le SP)
    Thread(target=start_server, args=[handle_watchdog_principal, PORT_WATCHDOG_PRINCIPAL]).start()
    
    # demarrage serveur 2 (communication avec le SS)
    Thread(target=start_server, args=[handle_watchdog_secondaire, PORT_WATCHDOG_SECONDAIRE]).start()
    
    # Boucle pour communiquer avec les serveurs
    while True:
        print("[WD] STATUS - UP\n")
        time.sleep(SLEEP_TIME * 3)

# Fonction qui gere le traitement lorsqu'un message client est recu par le serveur Socket
# Utilise l'asynchronisme
async def handle_client(reader, writer):
    data = await reader.read(100)
    message = data.decode()
    addr = writer.get_extra_info('peername')

    print(f"Message client recu de {addr!r} : {message!r}\n")

    # Message de retour
    writer.write(("Vous avez ecrit : " + data.decode()).encode())
    await writer.drain()
    writer.close()

# Fonction qui demarre le serveur Socket en asynchrone
async def run_server_socket(handle_fonction, port):
    server = await asyncio.start_server(handle_fonction, HOST, port)
    print(f'Serveur socket démarré sur : {server.sockets[0].getsockname()}\n')
    async with server:
        await server.serve_forever()
    return server

# Cette fonction fait appel a la fonction asynchrone permettant de demarrer le serveur
def start_server(handle_fonction, port) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Trigger run_server_socket() en asynchrone
    loop.run_until_complete(run_server_socket(handle_fonction, port))
    
    # Fermeture de la loop une fois terminee
    loop.close()

async def async_communiquer_watchdog(msg: str, port: int, pid: int) -> None:
    loop = asyncio.get_running_loop()

    on_con_lost = loop.create_future()

    transport, protocol = await loop.create_connection(
        lambda: EchoClientProtocol(msg, on_con_lost),
        '127.0.0.1', port)

    try:
        await on_con_lost
    finally:
        transport.close()
        
def communiquer_watchdog(msg: str, port: int, pid: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Trigger run_server_socket() en asynchrone
    loop.run_until_complete(async_communiquer_watchdog(msg, port, pid))
    
    # Fermeture de la loop une fois terminee
    loop.close()

# Traitement pour le processus pere (serveur principal SP)
# Le SP va utiliser le segment memoire partage et les tubes nommes pour communiquer avec son fils
# Le SP est egalement responsable du lancement du serveur socket pour les connexions clients
# et du lancement du WatchDog.
def processus_pere_traitement() -> None:

    # Gestion du Ctrl + C (arret du script + fermeture des flux)
    signal.signal(signal.SIGINT, signal_handler_exit)
    
    # Recuperation du segment memoire partage
    shm_parent = shared_memory.SharedMemory(name=shm.name)

    # Demarrage du WatchDog de facon securisee
    pid_watchdog = -1
    try:
        pid_watchdog = os.fork()
    except OSError as e:
        print("Creation du processus fils impossible, arret du script.\n" + str(e))
        signal_handler_exit(None, None)

    if pid_watchdog == 0: # Processus fils (WatchDog)
        processus_watchdog_traitement() # Traitement du watchdog
    elif pid_watchdog < 0: # Si erreur lors du fork()
        print("Erreur lors du fork() pour le watchdog")
    elif pid_watchdog > 1: # Pere
        Thread(target=start_server, args=[handle_client, PORT_SERVER_CLIENT]).start()
        
        connecte = False
        i = 0
        while True:
            try:
                if not connecte and i > 0:
                    Thread(target=communiquer_watchdog, args=["SP_OK", 1111, os.getpid()]).start()
                    connected = True
            except Exception as e:
                continue

            try:
                fifo1 = open(PATHTUBE1, "w")
                fifo2 = open(PATHTUBE2, "r")
            except Exception as e:
                print("Erreur lors de l'ouverture des tubes, arret du script.\n" + str(e))
                os._exit(1)
            
            fifo1.write("Message " + str(i) + " du processus principal !\n")
            fifo1.flush() # Pour regler les problemes de buffers lie aux tubes

            print("Message recu : " + fifo2.readline())

            fifo2.flush() # Pour regler les problemes de buffers lie aux tubes

            i += 1
            time.sleep(SLEEP_TIME)

# Traitement pour le processus fils (serveur secondaire)
# Communique en alternance avec le serveur principal via les tubes nommes et le segment memoire partage
def processus_fils_traitement() -> None:

    # Gestion du Ctrl + C
    signal.signal(signal.SIGINT, signal_handler_exit)
    
    # Recuperation du segment memoire partage
    shm_fils = shared_memory.SharedMemory(name=shm.name)
    
    connecte = False
    i = 0
    while True:
        try:
            if not connecte and i > 1:
                Thread(target=communiquer_watchdog, args=["SS_OK", 2222, os.getpid()]).start()
                connected = True
        except Exception as e:
            continue

        try:
            fifo1 = open(PATHTUBE1, "r")
            fifo2 = open(PATHTUBE2, "w")
        except Exception as e:
            print("Erreur lors de l'ouverture des tubes, arret du script.\n" + str(e))
            signal_handler_exit(None, None)

        print("Message recu : " + fifo1.readline())

        fifo1.flush() # Pour regler les problemes de buffers lie aux tubes
        fifo2.write("Message " + str(i) + " du processus secondaire !\n")
        fifo2.flush() # Pour regler les problemes de buffers lie aux tubes
        i += 1


""" ==================== [ MAIN ] ===================="""
""" 
    Partie principale du script
    Initialisation du segment memoire partage (SHM)
    Initialisation des tubes nommes
    Demarrage du serveur principal
    Demarrage du serveur secondaire               
                                                      """
"""==================================================="""

# Suppression de l'ancien segment memoire partage s'il y en a un
try:
    os.unlink(PATH_SHM)
except Exception:
    pass

# Creation du nouveau segment memoire partage
shm = shared_memory.SharedMemory(create=True, size=INI_SHM.nbytes, name="segment_mm")
b = np.ndarray(INI_SHM.shape, dtype=INI_SHM.dtype, buffer=shm.buf)
b[:] = INI_SHM[:]

# Initialisation des tubes nommes
creation_tubes()

# Creation d'un fork pour accueillir le serveur secondaire
pid = -1
try:
    pid = os.fork()
except OSError as e: # Si erreur il y a, le script s'arrete et ferme les fichiers actuellement ouverts
    print("Creation du processus fils impossible, arret du script.\n" + str(e))
    signal_handler_exit(None, None)

# Processus parent : serveur principal
if pid > 0:
    processus_pere_traitement()
elif pid == 0: # Processus fils, serveur secondaire
    processus_fils_traitement()
else: # Cas d'erreur lors du fork, ne devrait pas arriver, traitement de securite
    print("Erreur lors du fork()")
    signal_handler_exit(None, None)