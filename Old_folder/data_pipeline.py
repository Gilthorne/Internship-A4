import pandas as pd
import multiprocessing as mp
import os
import re
import subprocess
import json
from urllib.parse import urlparse
from datetime import datetime

class DataPipeline:
    """
    Pipeline to process data links from scientific articles:
    - Accepts DOIs or URLs
    - Validates sources (GitHub, Zenodo, Elsevier)
    - Checks for Excel/CSV files
    - Downloads available data
    """
    
    def __init__(self, max_workers=None):
        self.max_workers = max_workers or mp.cpu_count()
        self.results = []
    
    def normalize_link(self, link):
        """Convert DOI to URL if needed, return normalized link"""
        link = link.strip()
        
        if link.startswith('http://') or link.startswith('https://'):
            return link
        
        if re.match(r'^10\.\d{4,}/', link):
            return f"https://doi.org/{link}"
        
        if link.lower().startswith('doi:'):
            doi = link[4:].strip()
            return f"https://doi.org/{doi}"
        
        return link
    
    def extract_name(self, link):
        """Extract a simple name from the link"""
        parsed = urlparse(link)
        path = parsed.path
        
        if 'github.com' in parsed.netloc:
            parts = path.strip('/').split('/')
            if len(parts) >= 2:
                return f"{parts[0]}_{parts[1]}"
        
        elif 'zenodo.org' in parsed.netloc:
            match = re.search(r'/records?/(\d+)', path)
            if match:
                return f"zenodo_{match.group(1)}"
        
        elif 'doi.org' in parsed.netloc or any(d in parsed.netloc for d in ['elsevier.com', 'sciencedirect.com']):
            doi_match = re.search(r'10\.\d{4,}/[^\s/]+', link)
            if doi_match:
                doi = doi_match.group(0).replace('/', '_').replace('.', '_')
                return f"doi_{doi}"
        
        parts = path.strip('/').split('/')
        return parts[-1] if parts else parsed.netloc.replace('.', '_')
    
    def validate_source(self, link):
        """Check if link is from valid source"""
        if not link or not link.strip():
            return False, "empty"
        
        normalized = self.normalize_link(link)
        parsed = urlparse(normalized)
        domain = parsed.netloc.lower()
        
        if 'github.com' in domain:
            return True, "github"
        elif 'zenodo.org' in domain:
            return True, "zenodo"
        elif any(d in domain for d in ['elsevier.com', 'doi.org', 'sciencedirect.com']):
            return True, "elsevier"
        elif any(d in domain for d in ['datadryad.org', 'dryad', 'figshare', 'osf.io', 'dataverse']):
            return True, "generic"
        
        # Par défaut, essayer le scraper générique pour tout domaine inconnu
        return True, "generic"
    
    def call_scraper(self, scraper, link):
        """Call appropriate scraper and parse output"""
        try:
            normalized_link = self.normalize_link(link)
            
            result = subprocess.run(
                ['python', scraper, normalized_link],
                capture_output=True,
                text=True,
                timeout=180
            )
            
            stdout_lines = result.stdout.strip().split('\n')
            stderr_text = result.stderr.lower()
            
            if not stdout_lines:
                return False, False, 0
            
            # Parse stdout
            has_data = stdout_lines[0].lower() == "true"
            file_count = 0
            if len(stdout_lines) > 1 and stdout_lines[1].isdigit():
                file_count = int(stdout_lines[1])
            
            # Check stderr for errors indicating resource doesn't exist
            resource_exists = True
            error_indicators = [
                'error: http 404',
                'failed to retrieve metadata',
                'error accessing repo',
                'invalid github url',
                'unexpected api response'
            ]
            
            for indicator in error_indicators:
                if indicator in stderr_text:
                    resource_exists = False
                    break
            
            # If we got data, resource definitely exists
            if has_data or file_count > 0:
                resource_exists = True
            
            return resource_exists, has_data, file_count
            
        except subprocess.TimeoutExpired:
            print(f"Timeout: {scraper} - {link}")
            return False, False, 0
        except Exception as e:
            print(f"Error: {scraper} - {link}: {e}")
            return False, False, 0
    
    def process_link(self, link):
        """Process a single link through the pipeline"""
        normalized_link = self.normalize_link(link)
        
        result = {
            "original_input": link,
            "normalized_link": normalized_link,
            "name": self.extract_name(normalized_link),
            "source_valid": False,
            "source_type": "unknown",
            "has_data": False,
            "file_count": 0,
            "suitable": False,
            "processed_at": datetime.now().isoformat()
        }
        
        # Step 1: Validate source domain
        is_valid_domain, source_type = self.validate_source(link)
        
        if not is_valid_domain:
            result["source_type"] = source_type
            return result
        
        # Step 2: Call scraper
        if source_type == "github":
            resource_exists, has_data, file_count = self.call_scraper('github_scraper.py', normalized_link)
        elif source_type == "zenodo":
            resource_exists, has_data, file_count = self.call_scraper('zenodo_scraper.py', normalized_link)
        elif source_type == "elsevier":
            doi = link if not link.startswith('http') else normalized_link
            resource_exists, has_data, file_count = self.call_scraper('elsevier_complete_extractor.py', doi)
        elif source_type == "generic":
            resource_exists, has_data, file_count = self.call_scraper('generic_data_scraper.py', normalized_link)
        else:
            result["source_type"] = source_type
            return result
        
        # Step 3: Mark as valid if resource exists
        if resource_exists:
            result["source_valid"] = True
            result["source_type"] = source_type
            result["file_count"] = file_count
            result["has_data"] = has_data
            result["suitable"] = file_count > 0 or has_data
        else:
            result["source_valid"] = False
            result["source_type"] = "unknown"
        
        return result
    
    def run(self, links, output_file='results.xlsx'):
        """Execute pipeline with multiprocessing"""
        print(f"Processing {len(links)} links with {self.max_workers} workers...")
        
        valid_links = [link.strip() for link in links if link and link.strip()]
        
        if not valid_links:
            print("No valid links to process")
            return None
        
        with mp.Pool(processes=self.max_workers) as pool:
            results = pool.map(self.process_link, valid_links)
        
        df = pd.DataFrame(results)
        
        df.to_excel(output_file, index=False)
        print(f"\nResults saved: {output_file}")
        
        self.display_summary(df)
        self.save_json_summary(df, output_file.replace('.xlsx', '_summary.json'))
        
        return df
    
    def display_summary(self, df):
        """Display processing summary"""
        n_total = len(df)
        n_valid = df['source_valid'].sum()
        n_has_data = df['has_data'].sum()
        n_suitable = df['suitable'].sum()
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total links:     {n_total}")
        print(f"Valid sources:   {n_valid} ({n_valid/n_total*100:.1f}%)")
        print(f"Has data:        {n_has_data} ({n_has_data/n_total*100:.1f}%)")
        print(f"Suitable:        {n_suitable} ({n_suitable/n_total*100:.1f}%)")
        
        print("\nBy source type:")
        for source in df['source_type'].unique():
            count = (df['source_type'] == source).sum()
            has_data = ((df['source_type'] == source) & df['has_data']).sum()
            print(f"  {source:12} {count:3} links, {has_data:3} with data")
        
        total_files = df['file_count'].sum()
        print(f"\nTotal files found: {total_files}")
        print("=" * 60)
    
    def save_json_summary(self, df, filename):
        """Save summary as JSON"""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_links': len(df),
            'valid_sources': int(df['source_valid'].sum()),
            'has_data': int(df['has_data'].sum()),
            'suitable': int(df['suitable'].sum()),
            'total_files': int(df['file_count'].sum()),
            'by_source': {}
        }
        
        for source in df['source_type'].unique():
            summary['by_source'][source] = {
                'count': int((df['source_type'] == source).sum()),
                'has_data': int(((df['source_type'] == source) & df['has_data']).sum()),
                'files': int(df[df['source_type'] == source]['file_count'].sum())
            }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)


def read_links_file(file_path):
    """Read links from file with automatic encoding detection"""
    encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                links = [line.strip() for line in f if line.strip()]
            print(f"File read successfully with encoding: {encoding}")
            return links
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            print(f"Error with encoding {encoding}: {e}")
            continue
    
    print("Error: Could not read file with any known encoding")
    return []


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python data_pipeline.py <input_file> [max_workers]")
        print("\nInput file should contain one DOI or URL per line")
        print("\nExamples of valid inputs:")
        print("  10.1016/j.ecoinf.2025.103426")
        print("  https://doi.org/10.1016/j.ecoinf.2025.103426")
        print("  https://github.com/user/repo")
        print("  https://zenodo.org/records/17075237")
        print("\nUsage example:")
        print("  python data_pipeline.py dois.txt 4")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        sys.exit(1)
    
    links = read_links_file(input_file)
    
    if not links:
        print("No links found in file")
        sys.exit(1)
    
    print(f"Found {len(links)} entries in file")
    
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = f"results_{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    pipeline = DataPipeline(max_workers=max_workers)
    df = pipeline.run(links, output_file=output_file)


if __name__ == "__main__":
    main()