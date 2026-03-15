import os
import hashlib
from datetime import datetime
from pathlib import Path

# Optional: python-magic helps reliably identify file types.
# Windows users might need to install 'python-magic-bin' if 'python-magic' fails.
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False


def get_file_hash(filepath, chunk_size=8192):
    """Calculate SHA-256 hash of a file for exact duplicate detection."""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        print(f"Error hashing {filepath}: {e}")
        return None


def get_file_metadata(filepath):
    """Extract metadata (size, dates, type) from a specific file."""
    path = Path(filepath)
    if not path.exists() or not path.is_file():
        return None

    try:
        stat = path.stat()
        file_size = stat.st_size
        created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
        accessed_at = datetime.fromtimestamp(stat.st_atime).isoformat()
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        # Determine mime type
        mime_type = "unknown"
        if MAGIC_AVAILABLE:
            try:
                mime_type = magic.from_file(filepath, mime=True)
            except Exception:
                pass
        
        # Fallback to extension if magic fails or is unavailable
        if mime_type == "unknown":
            ext = path.suffix.lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                mime_type = 'image/' + ext[1:]
            elif ext in ['.mp4', '.mov', '.avi', '.mkv']:
                mime_type = 'video/' + ext[1:]
            elif ext in ['.pdf', '.doc', '.docx', '.txt', '.csv']:
                mime_type = 'document'
            elif ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
                mime_type = 'archive'

        # Categorize
        category = categorize_file(mime_type, path.suffix.lower())
        
        return {
            "path": str(path.absolute()),
            "name": path.name,
            "size_bytes": file_size,
            "created_at": created_at,
            "accessed_at": accessed_at,
            "modified_at": modified_at,
            "mime_type": mime_type,
            "category": category,
            "extension": path.suffix.lower()
        }
    except Exception as e:
        print(f"Error reading metadata for {filepath}: {e}")
        return None


def categorize_file(mime_type, extension):
    """Broad categorization for the dashboard and analytics."""
    if mime_type.startswith('image/'):
        return 'image'
    if mime_type.startswith('video/'):
        return 'video'
    if mime_type.startswith('audio/'):
        return 'audio'
    
    doc_exts = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv', '.rtf']
    if extension in doc_exts or 'document' in mime_type:
        return 'document'
        
    archive_exts = ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz']
    if extension in archive_exts or 'archive' in mime_type:
        return 'archive'
        
    code_exts = ['.js', '.jsx', '.ts', '.tsx', '.py', '.html', '.css', '.json', '.md', '.java', '.cpp', '.c']
    if extension in code_exts:
        return 'code'
        
    installer_exts = ['.exe', '.dmg', '.pkg', '.msi', '.deb', '.rpm']
    if extension in installer_exts:
        return 'installer'
        
    return 'other'


def scan_directory(directory_path, progress_callback=None):
    """
    Scans a directory recursively and yields file metadata.
    Does not compute hashes immediately to keep the initial scan fast.
    """
    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        return []

    results = []
    scanned_count = 0
    total_size = 0

    for root, _, files in os.walk(directory_path):
        for file in files:
            filepath = os.path.join(root, file)
            meta = get_file_metadata(filepath)
            
            if meta:
                results.append(meta)
                total_size += meta["size_bytes"]
                scanned_count += 1
                
                if progress_callback and scanned_count % 100 == 0:
                    progress_callback(scanned_count, total_size)
                    
    return results

