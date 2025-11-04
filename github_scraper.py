import re
import sys
import requests
import os
from urllib.parse import urlparse

def eprint(*args, **kwargs):
    """Print to stderr instead of stdout"""
    print(*args, file=sys.stderr, **kwargs)

def extract_repo_info(github_url):
    """Extract username and repo name from GitHub URL"""
    parsed_url = urlparse(github_url)
    if parsed_url.netloc != 'github.com':
        return None, None
    
    path_parts = [part for part in parsed_url.path.split('/') if part]
    if len(path_parts) < 2:
        return None, None
    
    return path_parts[0], path_parts[1]

def has_excel_csv_files(github_url):
    """Check if GitHub repo contains Excel/CSV files and return list"""
    username, repo = extract_repo_info(github_url)
    
    if not username or not repo:
        eprint(f"Invalid GitHub URL: {github_url}")
        return False, []
    
    api_url = f"https://api.github.com/repos/{username}/{repo}/git/trees/main?recursive=1"
    
    try:
        response = requests.get(api_url)
        
        if response.status_code == 404:
            api_url = f"https://api.github.com/repos/{username}/{repo}/git/trees/master?recursive=1"
            response = requests.get(api_url)
        
        if response.status_code != 200:
            eprint(f"Error accessing repo: {response.status_code}")
            return False, []
        
        data = response.json()
        
        if "tree" not in data:
            eprint("Unexpected API response structure")
            return False, []
        
        excel_csv_files = []
        for item in data["tree"]:
            if item["type"] == "blob":
                path = item["path"]
                if re.search(r'\.(xlsx?|csv)$', path, re.IGNORECASE):
                    branch = "main" if response.url.endswith("main?recursive=1") else "master"
                    excel_csv_files.append({
                        'path': path,
                        'filename': os.path.basename(path),
                        'url': f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{path}"
                    })
        
        return bool(excel_csv_files), excel_csv_files
    
    except Exception as e:
        eprint(f"Error: {str(e)}")
        return False, []

def download_files(file_list, directory):
    """Download Excel/CSV files to specified directory"""
    os.makedirs(directory, exist_ok=True)
    
    downloaded_files = []
    
    for file_info in file_list:
        try:
            url = file_info['url']
            filename = file_info['filename']
            
            filepath = os.path.join(directory, filename)
            base, ext = os.path.splitext(filepath)
            counter = 1
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                counter += 1
            
            response = requests.get(url)
            if response.status_code != 200:
                continue
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            downloaded_files.append(filepath)
            
        except Exception:
            continue
    
    return downloaded_files

def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('url', help='GitHub repository URL')
    parser.add_argument('--output-dir', default=None, help='Output directory')
    
    args = parser.parse_args()
    github_url = args.url
    
    username, repo = extract_repo_info(github_url)
    if not username or not repo:
        print("False")
        print("0")
        return False
    
    repo_name = f"{username}_{repo}"
    has_files, file_list = has_excel_csv_files(github_url)
    
    if has_files:
        # Déterminer le dossier de sortie
        if args.output_dir:
            output_dir = os.path.join(args.output_dir, repo_name)
        else:
            output_dir = f"downloads/{repo_name}"
        
        downloaded = download_files(file_list, output_dir)
        eprint(f"Downloaded {len(downloaded)}/{len(file_list)} files to {output_dir}")
    
    # Output format for pipeline
    print("True" if has_files else "False")
    print(len(file_list) if has_files else "0")
    
    return has_files

if __name__ == "__main__":
    main()