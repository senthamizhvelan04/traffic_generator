from flask import Flask, render_template, request, jsonify
from traffic_engine import TrafficGenerator

app = Flask(__name__)
generator = TrafficGenerator()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_traffic():
    config = request.json
    success, message = generator.start(config)
    return jsonify({'success': success, 'message': message})


@app.route('/api/stop', methods=['POST'])
def stop_traffic():
    success, message = generator.stop()
    return jsonify({'success': success, 'message': message})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(generator.get_stats())


if __name__ == '__main__':
    print('\n' + '=' * 60)
    print('  EC2 Traffic Generator')
    print('  Open http://localhost:5000 in your browser')
    print('=' * 60 + '\n')
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
