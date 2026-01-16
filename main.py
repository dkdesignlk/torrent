from flask import Flask, jsonify
from movie.baiscope import baiscope_blueprint

app = Flask(__name__)

# Register the baiscope blueprint
app.register_blueprint(baiscope_blueprint)

@app.route('/')
def home():
    return jsonify({
        'endpoints': {
            'baiscope': '/baiscope?url=<baiscope_page_url>',
            'example': '/baiscope?url=https://baiscope.lk/some-movie-sinhala-subtitles/'
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
