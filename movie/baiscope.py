from flask import Blueprint, jsonify, request
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import quote
import os
import time
import threading
import libtorrent as lt
import zipfile
import shutil

baiscope_blueprint = Blueprint('baiscope', __name__)

TMDB_API_KEY = 'e51447e837048930952e694908564da1'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
YTS_BASE_URL = 'https://yts.bz'

# Libtorrent session
ses = lt.session()
ses.listen_on(6881, 6891)
ses.start_dht()

downloads_path = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(downloads_path):
    os.makedirs(downloads_path)

def scrape_baiscope_page(target_url):
    """Scrape Baiscope page for movie data"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(target_url, headers=headers, timeout=15)
        html = response.text
        
        # Extract IMDB ID
        imdb_id = None
        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', html, re.IGNORECASE)
        if imdb_match:
            imdb_id = imdb_match.group(1)
        
        # Extract subtitle download URL
        subtitle_url = None
        subtitle_match = re.search(r'href="([^"]*\/Downloads\/\d+\/[^"]*)"', html, re.IGNORECASE)
        if subtitle_match:
            subtitle_url = subtitle_match.group(1)
            if subtitle_url.startswith('/'):
                parsed_url = requests.utils.urlparse(target_url)
                subtitle_url = f"{parsed_url.scheme}://{parsed_url.netloc}{subtitle_url}"
        
        # Extract movie name from title
        movie_name = None
        title_match = re.search(r'<title>([^<]+?)\s*(?:\||Sinhala)', html, re.IGNORECASE)
        if title_match:
            movie_name = title_match.group(1)
            movie_name = re.sub(r'\s+Sinhala Subtitles?', '', movie_name, flags=re.IGNORECASE)
            movie_name = re.sub(r'\s*\[.*?\]', '', movie_name)
            movie_name = re.sub(r'\s*\(.*?\)', '', movie_name)
            movie_name = re.sub(r'\s*\|.*$', '', movie_name, flags=re.IGNORECASE)
            movie_name = movie_name.strip()
            
            year_match = re.search(r'\((\d{4})\)', title_match.group(1))
            if year_match:
                movie_name = f"{movie_name} {year_match.group(1)}"
        
        if not movie_name:
            h1_match = re.search(r'<h1[^>]*class="[^"]*cm-entry-title[^"]*"[^>]*>\s*([^<]+)', html, re.IGNORECASE)
            if h1_match:
                movie_name = h1_match.group(1)
                movie_name = re.sub(r'\s+Sinhala Subtitles?', '', movie_name, flags=re.IGNORECASE)
                movie_name = re.sub(r'\s*\[.*?\]', '', movie_name)
                movie_name = re.sub(r'\s*\(.*?\)', '', movie_name)
                movie_name = re.sub(r'\s*\|.*$', '', movie_name, flags=re.IGNORECASE)
                movie_name = movie_name.strip()
                
                year_match = re.search(r'\((\d{4})\)', h1_match.group(1))
                if year_match:
                    movie_name = f"{movie_name} {year_match.group(1)}"
        
        return {
            'movieName': movie_name or 'Unknown',
            'imdbId': imdb_id,
            'subtitleUrl': subtitle_url
        }
        
    except Exception as e:
        raise Exception(f'Failed to scrape page: {str(e)}')

def get_movie_details_tmdb(imdb_id):
    """Get movie details from TMDB"""
    try:
        url = f"{TMDB_BASE_URL}/find/{imdb_id}"
        params = {'api_key': TMDB_API_KEY, 'external_source': 'imdb_id'}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get('movie_results'):
            movie = data['movie_results'][0]
            return {
                'title': movie['title'],
                'year': movie['release_date'][:4] if movie.get('release_date') else '',
                'imdb_id': imdb_id
            }
    except:
        pass
    return None

def create_magnet_link(torrent_hash, movie_name):
    """Create magnet link"""
    encoded_name = quote(movie_name)
    trackers = [
        'udp://open.stealth.si:80/announce',
        'udp://tracker.opentrackr.org:1337/announce',
        'udp://tracker.torrent.eu.org:451/announce',
        'udp://exodus.desync.com:6969/announce',
        'udp://tracker.moeking.me:6969/announce'
    ]
    
    magnet = f"magnet:?xt=urn:btih:{torrent_hash}&dn={encoded_name}"
    for tracker in trackers:
        magnet += f"&tr={tracker}"
    return magnet

def search_yts_by_imdb(imdb_id):
    """Search YTS using IMDB ID"""
    try:
        tmdb_movie = get_movie_details_tmdb(imdb_id)
        if not tmdb_movie:
            return None
        
        title = tmdb_movie['title']
        year = tmdb_movie['year']
        
        search_query = quote(title)
        url = f"{YTS_BASE_URL}/browse-movies/{search_query}/all/all/0/latest"
        if year:
            url += f"/{year}/all"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        movie_wrap = soup.find('div', class_='browse-movie-wrap')
        if not movie_wrap:
            return None
        
        link = movie_wrap.find('a', class_='browse-movie-link')
        if not link:
            return None
        
        movie_url = link.get('href', '')
        
        response = requests.get(movie_url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_elem = soup.find('h1')
        movie_title = title_elem.text.strip() if title_elem else ''
        
        year_elem = soup.find('h2')
        movie_year = year_elem.text.strip() if year_elem else ''
        
        torrent_divs = soup.find_all('div', class_='modal-torrent')
        
        best_torrent = None
        best_quality = 0
        
        for div in torrent_divs:
            try:
                quality_elem = div.find('div', class_='modal-quality')
                if not quality_elem:
                    continue
                
                quality_text = quality_elem.text.strip()
                if '3D' in quality_text:
                    continue
                
                quality = quality_text.split('.')[0]
                
                download_link = div.find('a', rel='nofollow')
                if not download_link:
                    continue
                
                torrent_url = download_link.get('href', '')
                hash_match = re.search(r'/([A-F0-9]{40})', torrent_url, re.IGNORECASE)
                if not hash_match:
                    continue
                
                torrent_hash = hash_match.group(1)
                
                tech_specs = div.find_all('p', class_='quality-size')
                seeds = 0
                
                for spec in tech_specs:
                    text = spec.text.strip()
                    if 'peer' in text.lower():
                        seed_match = re.search(r'(\d+)', text)
                        if seed_match:
                            seeds = int(seed_match.group(1))
                
                quality_val = 0
                if '2160p' in quality or '4K' in quality:
                    quality_val = 2160
                elif '1080p' in quality:
                    quality_val = 1080
                
                if quality_val > best_quality:
                    best_quality = quality_val
                    movie_name = f"{movie_title} ({movie_year}) [{quality}] [YTS]"
                    magnet = create_magnet_link(torrent_hash, movie_name)
                    best_torrent = {
                        'quality': quality,
                        'magnet': magnet,
                        'movie_name': movie_title,
                        'year': movie_year
                    }
            except:
                continue
        
        return best_torrent
        
    except Exception as e:
        print(f"YTS search error: {e}")
        return None

def download_subtitle(subtitle_url, save_folder, movie_name):
    """Download and extract subtitle"""
    try:
        print(f"\n📥 Downloading subtitle from: {subtitle_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(subtitle_url, headers=headers, timeout=30, stream=True)
        
        zip_path = os.path.join(save_folder, 'temp_subtitle.zip')
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        print("✅ Subtitle downloaded. Extracting...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if file.endswith('.srt'):
                    zip_ref.extract(file, save_folder)
                    extracted_path = os.path.join(save_folder, file)
                    final_path = os.path.join(save_folder, f"{movie_name}.srt")
                    
                    if os.path.exists(final_path):
                        os.remove(final_path)
                    
                    shutil.move(extracted_path, final_path)
                    print(f"✅ Subtitle saved: {movie_name}.srt")
                    
                    if os.path.dirname(extracted_path) != save_folder:
                        try:
                            shutil.rmtree(os.path.dirname(extracted_path))
                        except:
                            pass
                    break
        
        os.remove(zip_path)
        return True
        
    except Exception as e:
        print(f"❌ Subtitle download error: {str(e)}")
        return False

def download_movie_torrent(magnet_link, save_folder, movie_name):
    """Download movie using libtorrent (video file only)"""
    try:
        print(f"\n🎬 Starting movie download...")
        print(f"📁 Save location: {save_folder}")
        
        params = {
            'save_path': save_folder,
            'storage_mode': lt.storage_mode_t(2),
        }
        
        handle = lt.add_magnet_uri(ses, magnet_link, params)
        
        print("⏳ Getting metadata...")
        while not handle.has_metadata():
            time.sleep(1)
        
        torrent_info = handle.get_torrent_info()
        files = torrent_info.files()
        
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']
        video_file_index = -1
        largest_size = 0
        
        for i in range(files.num_files()):
            file_path = files.file_path(i)
            file_size = files.file_size(i)
            
            if any(file_path.lower().endswith(ext) for ext in video_extensions):
                if file_size > largest_size:
                    largest_size = file_size
                    video_file_index = i
        
        if video_file_index == -1:
            print("❌ No video file found in torrent")
            ses.remove_torrent(handle)
            return False
        
        for i in range(files.num_files()):
            if i != video_file_index:
                handle.file_priority(i, 0)
            else:
                handle.file_priority(i, 7)
        
        video_file_path = files.file_path(video_file_index)
        print(f"🎥 Downloading: {os.path.basename(video_file_path)}")
        
        while handle.status().state != lt.torrent_status.seeding:
            s = handle.status()
            
            progress = s.progress * 100
            download_rate = s.download_rate / 1024 / 1024
            peers = s.num_peers
            
            print(f"\r📊 Progress: {progress:.1f}% | Speed: {download_rate:.2f} MB/s | Peers: {peers}", end='', flush=True)
            
            if progress >= 99.9:
                break
            
            time.sleep(1)
        
        print("\n✅ Movie download complete!")
        
        original_path = os.path.join(save_folder, video_file_path)
        new_path = os.path.join(save_folder, f"{movie_name}{os.path.splitext(video_file_path)[1]}")
        
        if os.path.exists(original_path):
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(original_path, new_path)
            print(f"📝 Renamed to: {os.path.basename(new_path)}")
        
        ses.remove_torrent(handle)
        return True
        
    except Exception as e:
        print(f"\n❌ Movie download error: {str(e)}")
        return False

def start_download_process(imdb_id, movie_name, magnet_link, subtitle_url):
    """Start background download process"""
    try:
        save_folder = os.path.join(downloads_path, imdb_id)
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        
        print(f"\n{'='*60}")
        print(f"🎬 Movie: {movie_name}")
        print(f"🆔 IMDB ID: {imdb_id}")
        print(f"{'='*60}")
        
        if subtitle_url:
            download_subtitle(subtitle_url, save_folder, movie_name)
        
        if magnet_link:
            download_movie_torrent(magnet_link, save_folder, movie_name)
        
        print(f"\n{'='*60}")
        print(f"✅ All downloads complete!")
        print(f"📁 Location: {save_folder}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ Download process error: {str(e)}\n")

@baiscope_blueprint.route('/baiscope')
def baiscope_handler():
    """Handle /baiscope?url=<url> requests"""
    try:
        url = request.args.get('url')
        
        if not url:
            return jsonify({
                'error': 'Missing URL parameter. Use ?url=<baiscope_page_url>'
            }), 400
        
        scraped_data = scrape_baiscope_page(url)
        
        if not scraped_data['imdbId']:
            return jsonify({
                'success': False,
                'error': 'IMDB ID not found'
            }), 404
        
        torrent_data = search_yts_by_imdb(scraped_data['imdbId'])
        
        if not torrent_data:
            return jsonify({
                'success': False,
                'error': 'Torrent not found'
            }), 404
        
        thread = threading.Thread(
            target=start_download_process,
            args=(
                scraped_data['imdbId'],
                torrent_data['movie_name'],
                torrent_data['magnet'],
                scraped_data['subtitleUrl']
            )
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Downloading started! Check terminal for progress.',
            'data': {
                'movieName': torrent_data['movie_name'],
                'year': torrent_data['year'],
                'quality': torrent_data['quality'],
                'imdbId': scraped_data['imdbId'],
                'saveLocation': f"downloads/{scraped_data['imdbId']}"
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
