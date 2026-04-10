from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__)

# Serve the main index file from templates folder
@app.route('/')
def index():
    return render_template('index.html')

# Flask automatically serves files from 'static/' folder at '/static/...'
# But if you want to keep the root path for specific reasons (not recommended but for compatibility),
# you can add routes here. Let's go with standard Flask static handling.

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5100))
    # Render 배포 환경을 위한 0.0.0.0 바인딩 추가
    app.run(host='0.0.0.0', port=port)
