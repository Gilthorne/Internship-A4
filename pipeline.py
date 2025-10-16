import json
import time
from datetime import datetime

class Pipeline:
    def __init__(self, name="Ma Pipeline"):
        self.name = name
        self.steps = []
        self.results = []
        
    def add_step(self, name, function):
        """Ajoute une étape à la pipeline"""
        self.steps.append({
            'name': name,
            'function': function
        })
        return self
    
    def run(self, input_data):
        """Exécute toutes les étapes de la pipeline"""
        print(f"\n{'='*60}")
        print(f"Démarrage de la pipeline: {self.name}")
        print(f"{'='*60}\n")
        
        data = input_data
        total_start = time.time()
        
        for i, step in enumerate(self.steps, 1):
            print(f"[Étape {i}/{len(self.steps)}] {step['name']}")
            print(f"{'-'*60}")
            
            step_start = time.time()
            try:
                data = step['function'](data)
                step_time = time.time() - step_start
                
                result = {
                    'step': step['name'],
                    'status': 'success',
                    'time': round(step_time, 2)
                }
                self.results.append(result)
                
                print(f"✓ Terminé en {step_time:.2f}s\n")
                
            except Exception as e:
                step_time = time.time() - step_start
                result = {
                    'step': step['name'],
                    'status': 'error',
                    'error': str(e),
                    'time': round(step_time, 2)
                }
                self.results.append(result)
                
                print(f"✗ Erreur: {e}\n")
                break
        
        total_time = time.time() - total_start
        
        print(f"{'='*60}")
        print(f"Pipeline terminée en {total_time:.2f}s")
        print(f"{'='*60}\n")
        
        return data
    
    def summary(self):
        """Affiche un résumé de l'exécution"""
        print("\nRésumé de l'exécution:")
        for result in self.results:
            status = "✓" if result['status'] == 'success' else "✗"
            print(f"{status} {result['step']} - {result['time']}s")
            if 'error' in result:
                print(f"  Erreur: {result['error']}")

# Exemple d'utilisation
if __name__ == "__main__":
    def step1(data):
        print("Traitement des données...")
        time.sleep(1)
        return data
    
    def step2(data):
        print("Analyse en cours...")
        time.sleep(1)
        return data
    
    pipeline = Pipeline("Test Pipeline")
    pipeline.add_step("Chargement", step1)
    pipeline.add_step("Analyse", step2)
    
    result = pipeline.run({"input": "test"})
    pipeline.summary()
