import requests
import re
import os
import time

def download_dryad_files_via_api(doi_or_url, output_dir="dryad_downloads"):
    """Télécharge les fichiers via l'API Dryad v2"""
    
    # Extraire le DOI
    doi_match = re.search(r'10\.5061/dryad\.[a-z0-9]+', doi_or_url)
    if not doi_match:
        print("DOI Dryad non trouvé")
        return []
    
    doi = doi_match.group(0)
    print(f"DOI: {doi}")
    
    # Encoder le DOI pour l'URL
    doi_encoded = doi.replace('/', '%2F')
    
    # API Dryad v2 - obtenir les métadonnées du dataset
    api_url = f"https://datadryad.org/api/v2/datasets/{doi_encoded}"
    print(f"Querying API: {api_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"API Error: HTTP {response.status_code}")
            return []
        
        data = response.json()
        print(f"✓ Dataset found: {data.get('title', 'Unknown')}")
        
        # Obtenir l'URL des fichiers
        if '_links' not in data or 'stash:files' not in data['_links']:
            print("No files link found in API response")
            return []
        
        files_url = data['_links']['stash:files']['href']
        print(f"\nFetching files list from: {files_url}")
        
        files_response = requests.get(files_url, headers=headers, timeout=30)
        
        if files_response.status_code != 200:
            print(f"Files API Error: HTTP {files_response.status_code}")
            return []
        
        files_data = files_response.json()
        
        # Extraire les fichiers CSV/Excel
        if '_embedded' not in files_data or 'stash:files' not in files_data['_embedded']:
            print("No files found in dataset")
            return []
        
        all_files = files_data['_embedded']['stash:files']
        
        # Filtrer pour CSV/Excel
        csv_excel_files = []
        for file_obj in all_files:
            filename = file_obj.get('path', '')
            if re.search(r'\.(csv|xlsx?)$', filename, re.IGNORECASE):
                csv_excel_files.append({
                    'filename': filename,
                    'size': file_obj.get('size', 0),
                    'id': file_obj.get('id'),
                    'download_url': file_obj.get('_links', {}).get('stash:file-download', {}).get('href')
                })
        
        print(f"\n✓ Found {len(csv_excel_files)} CSV/Excel files:")
        for f in csv_excel_files:
            size_mb = f['size'] / (1024 * 1024)
            print(f"  - {f['filename']} ({size_mb:.2f} MB)")
        
        # Créer le dossier de sortie
        os.makedirs(output_dir, exist_ok=True)
        
        # Télécharger chaque fichier
        downloaded = []
        
        for i, file_info in enumerate(csv_excel_files, 1):
            filename = file_info['filename']
            download_url = file_info['download_url']
            expected_size = file_info['size']
            
            print(f"\n[{i}/{len(csv_excel_files)}] Downloading: {filename}")
            print(f"URL: {download_url}")
            
            if not download_url:
                print("✗ No download URL available")
                continue
            
            try:
                # Télécharger via l'API
                response = requests.get(download_url, headers=headers, stream=True, timeout=120)
                
                if response.status_code == 200:
                    filepath = os.path.join(output_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        downloaded_bytes = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                    
                    actual_size = os.path.getsize(filepath)
                    size_mb = actual_size / (1024 * 1024)
                    
                    print(f"✓ Downloaded: {size_mb:.2f} MB")
                    
                    # Vérifier la taille
                    if expected_size > 0 and abs(actual_size - expected_size) > 1000:
                        print(f"⚠ Warning: Size mismatch (expected {expected_size}, got {actual_size})")
                    
                    downloaded.append(filepath)
                    
                    # Pause entre fichiers
                    if i < len(csv_excel_files):
                        time.sleep(2)
                
                elif response.status_code == 202:
                    print("⏳ File preparation in progress")
                    # Avec l'API, on peut attendre et réessayer
                    time.sleep(5)
                    
                    response = requests.get(download_url, headers=headers, stream=True, timeout=120)
                    if response.status_code == 200:
                        filepath = os.path.join(output_dir, filename)
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        actual_size = os.path.getsize(filepath)
                        size_mb = actual_size / (1024 * 1024)
                        print(f"✓ Downloaded (retry): {size_mb:.2f} MB")
                        downloaded.append(filepath)
                    else:
                        print(f"✗ Still HTTP {response.status_code} after retry")
                else:
                    print(f"✗ HTTP {response.status_code}")
            
            except Exception as e:
                print(f"✗ Error: {e}")
        
        return downloaded
    
    except Exception as e:
        print(f"Error: {e}")
        return []


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python dryad_api_download.py <DOI_or_URL> [output_dir]")
        print("\nExample:")
        print("  python dryad_api_download.py 10.5061/dryad.2547d7x46")
        print("  python dryad_api_download.py https://doi.org/10.5061/dryad.2547d7x46")
        sys.exit(1)
    
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "dryad_downloads"
    
    print("=" * 60)
    print("DRYAD API DOWNLOADER")
    print("=" * 60)
    
    files = download_dryad_files_via_api(sys.argv[1], output_dir)
    
    print(f"\n{'='*60}")
    print(f"✅ Downloaded {len(files)} files total")
    print(f"📁 Location: {os.path.abspath(output_dir)}")
    
    if files:
        print(f"\nDownloaded files:")
        total_size = 0
        for f in files:
            size = os.path.getsize(f)
            total_size += size
            size_mb = size / (1024 * 1024)
            print(f"  - {os.path.basename(f)}: {size_mb:.2f} MB")
        
        total_mb = total_size / (1024 * 1024)
        print(f"\nTotal size: {total_mb:.2f} MB")
    
    print(f"{'='*60}")