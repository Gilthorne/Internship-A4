import urllib.request
import re
import sys

def extract_mendeley_id(url):
    """Extrait l'ID du dataset Mendeley depuis une URL"""
    pattern = r'data\.mendeley\.com/datasets/([^/\s]+)'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

def check_mendeley_data(url):
    """Vérifie si un lien Mendeley contient des données"""
    dataset_id = extract_mendeley_id(url)
    
    if not dataset_id:
        print("URL Mendeley non valide")
        return
    
    print(f"Analyse du dataset Mendeley: {dataset_id}")
    print(f"URL: {url}")
    
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            html_content = response.read().decode('utf-8')
        
        # Chercher les mentions de fichiers Excel/CSV dans le HTML
        excel_csv_pattern = r'\.(?:xlsx?|csv)\b'
        matches = re.findall(excel_csv_pattern, html_content, re.IGNORECASE)
        
        file_count = len(set(matches))
        
        print(f"\n{file_count} fichier(s) Excel/CSV trouvé(s)")
        
    except Exception as e:
        print(f"Erreur lors de l'accès à Mendeley: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python mendeley_scraper.py <MENDELEY_URL>")
        print("Exemple: python mendeley_scraper.py https://data.mendeley.com/datasets/abc123")
        return
    
    check_mendeley_data(sys.argv[1])

if __name__ == "__main__":
    main()
