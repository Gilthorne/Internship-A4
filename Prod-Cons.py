import threading
import queue
import time
import random

# --- Paramètres de la simulation ---

# Le nombre de threads qui vont "traiter" les papiers.
NUM_CONSUMERS = 5

# La taille maximale de la file d'attente. Si elle est pleine, le producteur attendra.
QUEUE_MAX_SIZE = 5

# Le nombre total d'éléments que nous allons simuler.
# Imaginez que c'est 5 millions, mais nous utilisons 30 pour l'exemple.
TOTAL_ITEMS_TO_PRODUCE = 300


def producer(work_queue: queue.Queue):
    """
    Le Producteur.
    Son rôle est de lire les données (ici, simuler leur création) et de les
    mettre dans la file d'attente partagée (work_queue).
    """
    thread_name = threading.current_thread().name
    print(f"[{thread_name}] Démarrage.")

    for item_id in range(TOTAL_ITEMS_TO_PRODUCE):
        # Simule la lecture depuis une base de données ou un fichier (un peu de temps)
        time.sleep(random.uniform(0.05, 0.2))

        item = {'id': item_id, 'data': f'Données du papier #{item_id}'}
        
        # C'est l'étape clé : on met l'élément dans la file.
        # Si la file est pleine (atteint QUEUE_MAX_SIZE), l'appel `put()`
        # va BLOQUER et attendre qu'un consommateur libère une place.
        work_queue.put(item)
        print(f"[{thread_name}] 🟢 A produit et ajouté l'item #{item_id}. Taille de la file: {work_queue.qsize()}")

    # Une fois que le producteur a terminé, il doit le signaler aux consommateurs
    # pour qu'ils puissent s'arrêter proprement.
    # On ajoute un 'None' (un "sentinel") pour chaque thread consommateur.
    print(f"[{thread_name}] A fini de produire. Envoi des signaux de fin.")
    for _ in range(NUM_CONSUMERS):
        work_queue.put(None)
    
    print(f"[{thread_name}] Terminé.")


def consumer(work_queue: queue.Queue):
    """
    Le Consommateur.
    Son rôle est de prendre des éléments de la file et de les traiter.
    Il tourne en boucle jusqu'à recevoir un signal de fin (None).
    """
    thread_name = threading.current_thread().name
    print(f"[{thread_name}] Démarrage.")

    while True:
        # C'est l'étape clé : on prend un élément de la file.
        # Si la file est vide, l'appel `get()` va BLOQUER et attendre
        # que le producteur ajoute un nouvel élément.
        item = work_queue.get()

        # On vérifie si on a reçu le signal de fin (le "sentinel")
        if item is None:
            print(f"[{thread_name}] Signal de fin reçu. Arrêt.")
            break # Sortir de la boucle while

        # Simule le traitement de l'élément (appel API, calcul, etc.)
        print(f"[{thread_name}]   -> Commence à traiter l'item #{item['id']}...")
        time.sleep(random.uniform(0.3, 1.0))
        print(f"[{thread_name}]   <- A fini de traiter l'item #{item['id']}. Taille de la file: {work_queue.qsize()}")
        
    print(f"[{thread_name}] Terminé.")


if __name__ == "__main__":
    start_time = time.time()

    # 1. Création de la file d'attente partagée avec une taille maximale.
    work_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)

    # 2. Création et démarrage du thread Producteur.
    #    On le met en mode "daemon" pour qu'il ne bloque pas la fin du programme en cas d'erreur.
    producer_thread = threading.Thread(
        target=producer, 
        args=(work_queue,), 
        name="Producteur",
        daemon=True
    )
    producer_thread.start()

    # 3. Création et démarrage du pool de threads Consommateurs.
    consumer_threads = []
    for i in range(NUM_CONSUMERS):
        consumer_thread = threading.Thread(
            target=consumer, 
            args=(work_queue,),
            name=f"Consommateur-{i}"
        )
        consumer_thread.start()
        consumer_threads.append(consumer_thread)

    # 4. Le thread principal attend que tous les consommateurs aient terminé leur travail.
    #    On n'a pas besoin d'attendre le producteur car les consommateurs ne s'arrêteront
    #    que lorsque le producteur aura fini et envoyé les signaux.
    for t in consumer_threads:
        t.join() # Bloque jusqu'à ce que ce thread soit terminé.

    print("\nToutes les tâches sont terminées.")
    print("--- %s seconds ---" % (time.time() - start_time))
