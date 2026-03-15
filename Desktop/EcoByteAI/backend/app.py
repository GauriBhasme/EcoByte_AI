from flask import Flask, jsonify, request
from flask_cors import CORS
import time
import random

app = Flask(__name__)
CORS(app)

import threading

# Import the new scanner service
from services import scanner

# Global dictionary to store scan job results and progress in-memory for MVP
scan_jobs = {}
scan_results = {}

@app.route('/api/upload', methods=['POST'])
def upload_files():
    # In a real cloud app, process request.files.
    # For this local scanner MVP, we'll accept a 'directory' path to scan instead.
    data = request.json or {}
    directory = data.get('directory', str(Path.home() / 'Downloads'))
    return jsonify({"message": "Source configured", "directory": directory}), 200

def run_scan_background(job_id, directory):
    try:
        def update_progress(count, size):
            # Capping progress at 90% during scan phase; remaining 10% is for processing results
            scan_jobs[job_id]["progress"] = min(90, int((count / max(1, count)) * 90))

        # Perform the actual directory scan
        results = scanner.scan_directory(directory, progress_callback=update_progress)
        
        # Save results globally
        scan_results[job_id] = results
        
        # Mark Complete
        scan_jobs[job_id]["progress"] = 100
        scan_jobs[job_id]["status"] = "completed"
        scan_jobs[job_id]["files_scanned"] = len(results)
    except Exception as e:
        scan_jobs[job_id]["status"] = "failed"
        scan_jobs[job_id]["error"] = str(e)


@app.route('/api/scan/start', methods=['POST'])
def start_scan():
    job_id = str(int(time.time() * 1000))
    scan_jobs[job_id] = {"status": "running", "progress": 0, "files_scanned": 0}
    
    # Optional directory path parameter
    data = request.json or {}
    # Default to scanning User's Downloads folder if no path is provided
    from pathlib import Path
    directory = data.get('directory', str(Path.home() / 'Downloads'))

    # Start the scan in a background thread so the request returns immediately
    thread = threading.Thread(target=run_scan_background, args=(job_id, directory))
    thread.daemon = True
    thread.start()
    
    return jsonify({"jobId": job_id, "message": "Scan started", "directory": directory}), 200

@app.route('/api/scan/status/<job_id>', methods=['GET'])
def scan_status(job_id):
    job = scan_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
            
    return jsonify(job), 200

def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_names = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    # If no scans have run, return zeroes
    if not scan_results:
        return jsonify({
            "stats": [
                {"id": "total_files", "title": "Total Files", "value": "0", "change": "0"},
                {"id": "total_size", "title": "Total Size", "value": "0 B", "change": "0 B"},
                {"id": "images", "title": "Images", "value": "0", "change": "0", "positive": False},
                {"id": "videos", "title": "Videos", "value": "0", "change": "0"},
                {"id": "docs", "title": "Documents", "value": "0", "change": "0"}
            ]
        }), 200

    # Get the latest completed scan result
    latest_job_id = list(scan_results.keys())[-1]
    files = scan_results[latest_job_id]

    total_size = sum(f["size_bytes"] for f in files)
    
    images_count = sum(1 for f in files if f["category"] == "image")
    videos_count = sum(1 for f in files if f["category"] == "video")
    docs_count = sum(1 for f in files if f["category"] == "document")

    return jsonify({
        "stats": [
            {"id": "total_files", "title": "Total Files", "value": f"{len(files):,}", "change": "New Scan"},
            {"id": "total_size", "title": "Total Size", "value": format_size(total_size), "change": "New Scan"},
            {"id": "images", "title": "Images", "value": f"{images_count:,}", "change": "--", "positive": False},
            {"id": "videos", "title": "Videos", "value": f"{videos_count:,}", "change": "--"},
            {"id": "docs", "title": "Documents", "value": f"{docs_count:,}", "change": "--"}
        ]
    }), 200

@app.route('/api/dashboard/insights', methods=['GET'])
def get_dashboard_insights():
    return jsonify({
        "insights": [
            {"type": "warning", "message": "500MB of cache can be cleared to improve performance."},
            {"type": "info", "message": "You have 4.2GB of old installers."},
            {"type": "success", "message": "12 duplicate videos found. Potential saving: 2.1GB."}
        ]
    }), 200

# ---------------------------------------------------------
# 3. Storage Insights & File Categories
# ---------------------------------------------------------
@app.route('/api/insights/summary', methods=['GET'])
def get_insights_summary():
    return jsonify({
        "junk_files": {"size": "1.2 GB", "trend": "+12% vs last wk"},
        "large_files": {"size": "8.5 GB", "trend": "Scan 2h ago"},
        "old_downloads": {"size": "2.4 GB", "trend": "6+ mo old"}
    }), 200

from collections import defaultdict
from services import scanner

@app.route('/api/insights/duplicates', methods=['GET'])
def get_duplicates():
    if not scan_results:
        return jsonify({"groups": []}), 200

    latest_job_id = list(scan_results.keys())[-1]
    files = scan_results[latest_job_id]

    # Step 1: Group by file size to quickly find potential duplicates
    size_groups = defaultdict(list)
    for f in files:
        if f["size_bytes"] > 0: # Ignore 0-byte files
            size_groups[f["size_bytes"]].append(f)
            
    # Step 2: For groups with >1 file of the same size, calculate SHA-256
    duplicate_groups = []
    group_id = 1
    
    for size, identical_size_files in size_groups.items():
        if len(identical_size_files) > 1:
            hash_groups = defaultdict(list)
            for file_metadata in identical_size_files:
                # Hash the file physically now (it wasn't done during the fast initial scan)
                file_hash = scanner.get_file_hash(file_metadata["path"])
                if file_hash:
                    hash_groups[file_hash].append(file_metadata)
                    
            # Wrap actual confirmed duplicate groups for the frontend
            for file_hash, identical_hash_files in hash_groups.items():
                if len(identical_hash_files) > 1:
                    wasted_space = size * (len(identical_hash_files) - 1)
                    
                    formatted_files = []
                    for idx, f in enumerate(identical_hash_files):
                        formatted_files.append({
                            "path": f["path"],
                            "size": format_size(f["size_bytes"]),
                            "date": f["modified_at"][:10], # Truncate ISO string to YYYY-MM-DD
                            "selected": idx > 0 # Select all except the very first one for deletion
                        })
                        
                    duplicate_groups.append({
                        "id": group_id,
                        "name": identical_hash_files[0]["name"],
                        "wastedSpace": format_size(wasted_space),
                        "wastedSpaceBytes": wasted_space,
                        "files": formatted_files
                    })
                    group_id += 1
                    
    # Sort groups by most wasted space descending
    duplicate_groups.sort(key=lambda x: x["wastedSpaceBytes"], reverse=True)
    
    # Cap to top 20 for MVP performance reasons
    duplicate_groups = duplicate_groups[:20]

    return jsonify({"groups": duplicate_groups}), 200

@app.route('/api/insights/similar-images', methods=['GET'])
def get_similar_images():
    return jsonify({
        "groups": [
            {
                "id": 1,
                "name": "Group 1: Sunset Series",
                "count": "4 Images",
                "saving": "342 MB Potential Saving",
                "images": [
                    {"id": "img1", "src": "https://images.unsplash.com/photo-1495616811223-4d98c6e9c869?auto=format&fit=crop&q=80&w=400", "name": "IMG_8492.jpg", "meta": "4.2 MB • 4032 × 3024", "best": True},
                    {"id": "img2", "src": "https://images.unsplash.com/photo-1495616811223-4d98c6e9c869?auto=format&fit=crop&q=80&w=400&blur=10", "name": "IMG_8493.jpg", "meta": "3.8 MB • Blurred/Motion", "best": False}
                ]
            }
        ]
    }), 200

@app.route('/api/insights/large-files', methods=['GET'])
def get_large_files():
    if not scan_results:
        return jsonify({"files": []}), 200

    latest_job_id = list(scan_results.keys())[-1]
    files = scan_results[latest_job_id]

    # Filter files > 50MB for example, and sort by size descending
    large_files = [f for f in files if f["size_bytes"] > 50 * 1024 * 1024]
    large_files.sort(key=lambda x: x["size_bytes"], reverse=True)
    
    # Cap at top 50
    large_files = large_files[:50]

    # Map colors and icons based on categories for the frontend
    category_colors = {
        "video": "text-blue-500",
        "archive": "text-orange-500",
        "image": "text-purple-500",
        "document": "text-gray-500",
        "code": "text-green-500",
        "installer": "text-red-500",
        "other": "text-gray-400"
    }

    formatted_files = []
    for idx, f in enumerate(large_files):
        formatted_files.append({
            "id": idx + 1,
            "name": f["name"],
            "path": f["path"],
            "size": format_size(f["size_bytes"]),
            "rawSizeMB": round(f["size_bytes"] / (1024 * 1024), 2),
            "type": f["category"].capitalize(),
            "color": category_colors.get(f["category"], "text-gray-500"),
            "selected": False
        })

    return jsonify({"files": formatted_files}), 200

import os

@app.route('/api/files/delete', methods=['POST'])
def delete_files():
    data = request.json
    if not data or 'files' not in data:
        return jsonify({"error": "No files provided"}), 400

    files_to_delete = data.get("files", [])
    deleted_count = 0
    reclaimed_bytes = 0
    failed_files = []

    global global_reclaimed_bytes

    for file_path in files_to_delete:
        try:
            if os.path.exists(file_path):
                # Retrieve size before deleting
                size = os.path.getsize(file_path)
                os.remove(file_path)
                
                deleted_count += 1
                reclaimed_bytes += size
            else:
                failed_files.append({"path": file_path, "reason": "Not found"})
        except Exception as e:
            failed_files.append({"path": file_path, "reason": str(e)})

    # Increment global tracker
    global_reclaimed_bytes += reclaimed_bytes

    return jsonify({
        "success": True,
        "message": f"Successfully deleted {deleted_count} files",
        "detailed_results": {
            "deleted_count": deleted_count,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_str": format_size(reclaimed_bytes),
            "failed_count": len(failed_files),
            "failures": failed_files
        }
    }), 200

@app.route('/api/files/keep-best', methods=['POST'])
def keep_best():
    data = request.json
    group_id = data.get("group_id")
    return jsonify({"message": f"Kept best images for group {group_id}.", "deleted_count": 3}), 200

# ---------------------------------------------------------
# 4. Sustainability & Carbon Impact
# ---------------------------------------------------------
# Keep track of totally reclaimed storage globally (in a real app, from the database)
global_reclaimed_bytes = 0

@app.route('/api/sustainability/metrics', methods=['GET'])
def get_sustainability_metrics():
    # 1 GB of cloud storage = approx 0.002 kWh per month (varies wildly, standard estimate)
    # CO2 average = 0.385 kg per kWh
    
    reclaimed_gb = global_reclaimed_bytes / (1024 ** 3)
    kwh_saved = reclaimed_gb * 0.002 * 12 # Annualized
    co2_saved_kg = kwh_saved * 0.385
    trees_equivalent = co2_saved_kg / 21.0 # ~21kg absorbed by tree per yr
    
    # Calculate a simple 0-100 score based on how much was cleaned up relative to their total storage
    # If no scans, give a basic 50
    score = 50
    if scan_results:
        latest_job = list(scan_results.keys())[-1]
        total_size = sum(f["size_bytes"] for f in scan_results[latest_job])
        if total_size > 0:
            percentage_cleaned = (global_reclaimed_bytes / total_size) * 100
            score = min(100, int(50 + (percentage_cleaned * 5))) # 50 = baseline

    return jsonify({
        "co2_saved": {"value": f"{co2_saved_kg:.2f} kg", "subtext": f"Equivalent to driving {int(co2_saved_kg * 4)} miles"},
        "trees": {"value": f"{trees_equivalent:.1f} Trees", "subtext": "Planted to offset your cloud storage"},
        "energy": {"value": f"{kwh_saved:.1f} kWh", "subtext": f"Saved by cleaning {format_size(global_reclaimed_bytes)} of data"},
        "eco_score": score,
        "milestones": [
            {"title": "Cloud Connected", "date": "Just now", "desc": "Successfully connected Local Storage and ran the first scan."}
        ]
    }), 200

# ---------------------------------------------------------
# 5. Analytics Deep-Dive
# ---------------------------------------------------------
@app.route('/api/analytics/historical', methods=['GET'])
def get_historical_analytics():
    return jsonify({
        "data": [
            {"name": "SEP", "growth": 20, "cleanup": 5},
            {"name": "OCT", "growth": 22, "cleanup": 8},
            {"name": "NOV", "growth": 18, "cleanup": 12},
            {"name": "DEC", "growth": 25, "cleanup": 10},
            {"name": "JAN", "growth": 40, "cleanup": 15},
            {"name": "FEB", "growth": 55, "cleanup": 25}
        ]
    }), 200

@app.route('/api/analytics/datatypes', methods=['GET'])
def get_datatype_analytics():
    return jsonify({
        "images": {"growth": "+24%", "percentage": 85},
        "videos": {"growth": "+8%", "percentage": 40},
        "documents": {"growth": "-2%", "percentage": 25},
        "archives": {"growth": "+18%", "percentage": 60}
    }), 200

@app.route('/api/analytics/sources', methods=['GET'])
def get_source_analytics():
    return jsonify({
        "sources": [
            {
                "name": "Google Drive",
                "connected": "2 years ago",
                "used": "840.2 GB",
                "redundant": "124.5 GB",
                "efficiency": 82
            },
            {
                "name": "Local Storage (SSD)",
                "connected": "MacBook Pro 16\"",
                "used": "210.5 GB",
                "redundant": "42.1 GB",
                "efficiency": 91
            }
        ]
    }), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)