import requests
import sys
import re

def extract_repo_from_url(url):
    """
    Extracts the repository name (owner/name) from a GitHub URL.
    """
    pattern = r'github\.com/([^/]+/[^/]+)'
    match = re.search(pattern, url)
    
    if match:
        repo = match.group(1)
        repo = repo.split('?')[0].split('#')[0].rstrip('/')
        return repo
    return None

def find_csv_excel_in_repo(repo_name):
    """
    Finds all CSV and Excel files across all branches of a GitHub repository.
    """
    # Extensions to search for
    extensions = ('.csv', '.xlsx', '.xls')
    all_files = []
    
    try:
        # 1. Get all branches
        branches_url = f"https://api.github.com/repos/{repo_name}/branches"
        branches_response = requests.get(branches_url)
        branches_response.raise_for_status()
        branches = branches_response.json()
        
        print(f"Searching repository: {repo_name}")
        print(f"Branches found: {len(branches)}\n")
        
        # 2. For each branch, get the file tree
        for branch in branches:
            branch_name = branch['name']
            print(f"Analyzing branch '{branch_name}'...")
            
            tree_url = f"https://api.github.com/repos/{repo_name}/git/trees/{branch_name}?recursive=1"
            tree_response = requests.get(tree_url)
            
            if tree_response.status_code != 200:
                print(f"Unable to access this branch")
                continue
            
            tree_data = tree_response.json()
            branch_file_count = 0
            
            # 3. Filter CSV/Excel files
            for item in tree_data.get('tree', []):
                if item['type'] == 'blob':
                    file_path = item['path']
                    if file_path.lower().endswith(extensions):
                        file_url = f"https://github.com/{repo_name}/blob/{branch_name}/{file_path}"
                        all_files.append({
                            'url': file_url,
                            'path': file_path,
                            'branch': branch_name
                        })
                        branch_file_count += 1
            
            print(f"{branch_file_count} file(s) found\n")
        
        return all_files
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python find_spreadsheets_simple.py <github_url_or_repo>")
        print("Example: python find_spreadsheets_simple.py https://github.com/fivethirtyeight/data")
        sys.exit(1)
    
    input_value = sys.argv[1]
    
    # Check if it's a URL or directly the repo name
    if 'github.com' in input_value:
        repo = extract_repo_from_url(input_value)
        if not repo:
            print("Error: Invalid GitHub URL")
            sys.exit(1)
    else:
        repo = input_value
    
    files = find_csv_excel_in_repo(repo)
    
    print(f"\n{'='*60}")
    if files:
        print(f"Total: {len(files)} file(s) found:\n")
        for file_info in files:
            print(f"  {file_info['path']} (branch: {file_info['branch']})")
    else:
        print("No CSV or Excel files found.")
    print('='*60)