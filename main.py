import os
import time
import threading
import libtorrent as lt
import wget
from flask import Flask, request, jsonify
from flask_cors import CORS
from torf import Torrent
import uuid

app = Flask(__name__)
CORS(app)

# Global session and torrents storage
ses = lt.session()
ses.listen_on(6881, 6891)
ses.start_dht()

torrents = {}
save_path = os.path.join(os.getcwd(), 'downloads')

if not os.path.exists(save_path):
    os.makedirs(save_path)

# HTML embedded in the code
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="si">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Torrent Downloader</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 min-h-screen">
    <div class="container mx-auto px-4 py-8 max-w-5xl">
        <div class="bg-gray-800 rounded-lg shadow-xl p-6 border border-gray-700">
            <div class="flex items-center gap-3 mb-6 border-b border-gray-700 pb-4">
                <svg class="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path>
                </svg>
                <h1 class="text-3xl font-bold text-white">Torrent Downloader</h1>
            </div>

            <div id="error" class="hidden bg-red-900 border border-red-700 rounded-lg p-4 mb-6">
                <p class="text-red-200" id="error-text"></p>
            </div>

            <div class="space-y-4 mb-6">
                <div class="flex gap-3">
                    <input type="text" id="torrent-input" placeholder="Magnet link හෝ .torrent file URL එක paste කරන්න..."
                        class="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <button onclick="addTorrent()" id="add-btn"
                        class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold transition-colors flex items-center gap-2">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path>
                        </svg>
                        Download
                    </button>
                </div>
            </div>

            <div class="space-y-3">
                <div class="flex items-center gap-2 mb-3">
                    <svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                    </svg>
                    <h2 class="text-xl font-semibold text-white">Downloads</h2>
                </div>
                <div id="torrents-list"></div>
            </div>
        </div>

        <div class="mt-6 text-center text-gray-500 text-sm">
            <p>Downloads folder: <span class="text-gray-400 font-mono">./downloads</span></p>
            <p class="mt-1">Server port: <span class="text-blue-400 font-mono">3890</span></p>
        </div>
    </div>

    <script>
        async function addTorrent() {
            const input = document.getElementById('torrent-input');
            const btn = document.getElementById('add-btn');
            const link = input.value.trim();

            if (!link) {
                showError('කරුණාකර torrent link එකක් ඇතුළත් කරන්න');
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Adding...';

            try {
                const response = await fetch('/add-torrent', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ link })
                });

                const data = await response.json();

                if (data.success) {
                    input.value = '';
                    hideError();
                } else {
                    showError(data.error || 'Download එක add කරන්න බැහැ');
                }
            } catch (err) {
                showError('Server එකට connect වෙන්න බැහැ');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path></svg> Download';
            }
        }

        async function removeTorrent(id) {
            await fetch('/remove-torrent/' + id, { method: 'DELETE' });
        }

        async function fetchTorrents() {
            try {
                const response = await fetch('/torrents');
                const data = await response.json();
                renderTorrents(data.torrents || []);
            } catch (err) {
                console.error('Fetch error:', err);
            }
        }

        function renderTorrents(torrents) {
            const list = document.getElementById('torrents-list');
            
            if (torrents.length === 0) {
                list.innerHTML = '<div class="text-center py-16 text-gray-500 bg-gray-750 rounded-lg border border-gray-700"><svg class="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path></svg><p>Downloads නැහැ. Link එකක් add කරන්න!</p></div>';
                return;
            }

            list.innerHTML = torrents.map(t => `
                <div class="bg-gray-750 border border-gray-700 rounded-lg p-4 hover:bg-gray-700 transition-colors mb-3">
                    <div class="flex items-start justify-between mb-3">
                        <div class="flex-1 min-w-0">
                            <h3 class="text-white font-medium truncate">${t.name}</h3>
                            <p class="text-gray-400 text-sm mt-1">${t.state}</p>
                        </div>
                        <button onclick="removeTorrent('${t.id}')" class="text-red-400 hover:text-red-300 p-2 hover:bg-red-900 rounded-lg transition-colors ml-3">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                    </div>
                    <div class="space-y-2">
                        <div class="flex justify-between text-sm text-gray-400">
                            <span>${t.progress.toFixed(1)}%</span>
                            <span>${t.peers} peers</span>
                        </div>
                        <div class="w-full bg-gray-600 rounded-full h-2 overflow-hidden">
                            <div class="bg-blue-500 h-full transition-all duration-300" style="width: ${t.progress}%"></div>
                        </div>
                        <div class="flex justify-between text-sm text-gray-400">
                            <span>↓ ${(t.download_rate / 1000).toFixed(1)} kB/s</span>
                            <span>↑ ${(t.upload_rate / 1000).toFixed(1)} kB/s</span>
                        </div>
                        ${t.progress >= 100 ? '<div class="flex items-center gap-2 text-green-400 text-sm mt-2"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg><span>Download සම්පූර්ණයි!</span></div>' : ''}
                    </div>
                </div>
            `).join('');
        }

        function showError(msg) {
            document.getElementById('error').classList.remove('hidden');
            document.getElementById('error-text').textContent = msg;
        }

        function hideError() {
            document.getElementById('error').classList.add('hidden');
        }

        document.getElementById('torrent-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') addTorrent();
        });

        fetchTorrents();
        setInterval(fetchTorrents, 2000);
    </script>
</body>
</html>'''

def download_torrent(torrent_id, link):
    """Background thread to handle torrent download"""
    try:
        # Handle .torrent file
        if link.endswith('.torrent'):
            torrent_file = f'temp_{torrent_id}.torrent'
            if os.path.exists(torrent_file):
                os.remove(torrent_file)
            wget.download(link, torrent_file)
            t = Torrent.read(torrent_file)
            link = str(t.magnet(name=True, size=False, trackers=False, tracker=False))
            os.remove(torrent_file)
        
        params = {
            'save_path': save_path,
            'storage_mode': lt.storage_mode_t(2),
        }
        
        handle = lt.add_magnet_uri(ses, link, params)
        handle.set_sequential_download(0)
        
        torrents[torrent_id]['handle'] = handle
        torrents[torrent_id]['state'] = 'Downloading Metadata...'
        
        # Wait for metadata
        while not handle.has_metadata():
            if torrent_id not in torrents:
                return
            time.sleep(1)
        
        torrents[torrent_id]['name'] = handle.name()
        torrents[torrent_id]['state'] = 'Downloading...'
        
        # Download loop
        while handle.status().state != lt.torrent_status.seeding:
            if torrent_id not in torrents:
                ses.remove_torrent(handle)
                return
                
            s = handle.status()
            state_str = ['queued', 'checking', 'downloading metadata',
                        'downloading', 'finished', 'seeding', 'allocating']
            
            torrents[torrent_id].update({
                'progress': s.progress * 100,
                'download_rate': s.download_rate,
                'upload_rate': s.upload_rate,
                'peers': s.num_peers,
                'state': state_str[s.state]
            })
            
            time.sleep(2)
        
        torrents[torrent_id]['state'] = 'Seeding/Complete'
        torrents[torrent_id]['progress'] = 100
        
    except Exception as e:
        if torrent_id in torrents:
            torrents[torrent_id]['state'] = f'Error: {str(e)}'
            torrents[torrent_id]['error'] = str(e)

@app.route('/')
def index():
    """Serve the main HTML page"""
    return HTML_TEMPLATE

@app.route('/add-torrent', methods=['POST'])
def add_torrent():
    """Add a new torrent download"""
    try:
        data = request.get_json()
        link = data.get('link', '').strip()
        
        if not link:
            return jsonify({'success': False, 'error': 'Link එකක් ඇතුළත් කරන්න'}), 400
        
        torrent_id = str(uuid.uuid4())
        
        torrents[torrent_id] = {
            'id': torrent_id,
            'link': link,
            'name': 'Loading...',
            'progress': 0,
            'download_rate': 0,
            'upload_rate': 0,
            'peers': 0,
            'state': 'Starting...',
            'handle': None
        }
        
        # Start download in background thread
        thread = threading.Thread(target=download_torrent, args=(torrent_id, link))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'id': torrent_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/torrents', methods=['GET'])
def get_torrents():
    """Get all active torrents"""
    torrent_list = []
    for tid, tdata in torrents.items():
        torrent_list.append({
            'id': tid,
            'name': tdata.get('name', 'Unknown'),
            'progress': tdata.get('progress', 0),
            'download_rate': tdata.get('download_rate', 0),
            'upload_rate': tdata.get('upload_rate', 0),
            'peers': tdata.get('peers', 0),
            'state': tdata.get('state', 'Unknown')
        })
    return jsonify({'torrents': torrent_list})

@app.route('/remove-torrent/<torrent_id>', methods=['DELETE'])
def remove_torrent(torrent_id):
    """Remove a torrent"""
    try:
        if torrent_id in torrents:
            handle = torrents[torrent_id].get('handle')
            if handle:
                ses.remove_torrent(handle)
            del torrents[torrent_id]
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Torrent එක හමු වුණේ නැහැ'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Torrent Downloader Server Starting...")
    print("=" * 60)
    print(f"📁 Download Location: {save_path}")
    print(f"🌐 Web Interface: http://localhost:3890")
    print(f"⚡ Ready to download torrents!")
    print("=" * 60)
    app.run(host='0.0.0.0', port=3890, debug=False)