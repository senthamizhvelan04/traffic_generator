import threading
import time
import requests
import socket
import random
import string
from dataclasses import dataclass, field
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


@dataclass
class TrafficStats:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    active_threads: int = 0
    start_time: float = 0
    bytes_sent: int = 0
    requests_per_second: float = 0
    status_codes: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _recent_timestamps: list = field(default_factory=list, repr=False)

    def record_request(self, success: bool, status_code: int = 0, bytes_count: int = 0):
        with self._lock:
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
            self.bytes_sent += bytes_count
            if status_code:
                self.status_codes[str(status_code)] = self.status_codes.get(str(status_code), 0) + 1
            now = time.time()
            self._recent_timestamps.append(now)
            self._recent_timestamps = [t for t in self._recent_timestamps if now - t <= 5]
            if len(self._recent_timestamps) > 1:
                time_span = self._recent_timestamps[-1] - self._recent_timestamps[0]
                if time_span > 0:
                    self.requests_per_second = round(len(self._recent_timestamps) / time_span, 1)

    def to_dict(self):
        with self._lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            return {
                'total_requests': self.total_requests,
                'successful_requests': self.successful_requests,
                'failed_requests': self.failed_requests,
                'active_threads': self.active_threads,
                'elapsed_seconds': round(elapsed, 1),
                'bytes_sent': self.bytes_sent,
                'requests_per_second': self.requests_per_second,
                'status_codes': dict(self.status_codes),
            }


class TrafficGenerator:
    def __init__(self):
        self.is_running = False
        self.stats = TrafficStats()
        self.threads = []
        self._stop_event = threading.Event()

    def _generate_payload(self, size_kb=1):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=size_kb * 1024))

    def _build_url(self, target_ip, port, path='/'):
        protocol = 'https' if port == 443 else 'http'
        return f"{protocol}://{target_ip}:{port}{path}"

    def _worker_http(self, target_ip, port, method, duration, payload_size, paths, delay):
        end_time = time.time() + duration if duration > 0 else float('inf')
        session = requests.Session()
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
            'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        ]

        with self.stats._lock:
            self.stats.active_threads += 1

        try:
            while not self._stop_event.is_set() and time.time() < end_time:
                try:
                    path = random.choice(paths)
                    url = self._build_url(target_ip, port, path)
                    headers = {
                        'User-Agent': random.choice(user_agents),
                        'Accept': 'text/html,application/json,*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive',
                    }

                    bytes_count = 0
                    if method == 'GET':
                        params = {'_': str(time.time()), 'r': random.randint(1, 999999)}
                        resp = session.get(url, headers=headers, params=params, timeout=10, verify=False)
                    elif method == 'POST':
                        payload = self._generate_payload(payload_size)
                        bytes_count = len(payload)
                        headers['Content-Type'] = 'application/json'
                        resp = session.post(url, headers=headers, data=payload, timeout=10, verify=False)
                    elif method == 'HEAD':
                        resp = session.head(url, headers=headers, timeout=10, verify=False)
                    else:
                        resp = session.get(url, headers=headers, timeout=10, verify=False)

                    self.stats.record_request(True, resp.status_code, bytes_count)

                except requests.exceptions.RequestException:
                    self.stats.record_request(False, 0, 0)
                except Exception:
                    self.stats.record_request(False, 0, 0)

                if delay > 0:
                    time.sleep(delay / 1000.0)
        finally:
            with self.stats._lock:
                self.stats.active_threads -= 1

    def _worker_tcp(self, target_ip, port, duration, payload_size, delay):
        end_time = time.time() + duration if duration > 0 else float('inf')

        with self.stats._lock:
            self.stats.active_threads += 1

        try:
            while not self._stop_event.is_set() and time.time() < end_time:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    sock.connect((target_ip, port))
                    payload = self._generate_payload(payload_size).encode()
                    sock.send(payload)
                    self.stats.record_request(True, 0, len(payload))
                    sock.close()
                except Exception:
                    self.stats.record_request(False, 0, 0)

                if delay > 0:
                    time.sleep(delay / 1000.0)
        finally:
            with self.stats._lock:
                self.stats.active_threads -= 1

    def start(self, config):
        if self.is_running:
            return False, 'Traffic generation is already running'

        self._stop_event.clear()
        self.stats = TrafficStats()
        self.stats.start_time = time.time()
        self.threads = []
        self.is_running = True

        target_ip = config.get('target_ip', '').strip()
        port = int(config.get('port', 80))
        method = config.get('method', 'GET').upper()
        num_threads = int(config.get('threads', 10))
        duration = int(config.get('duration', 60))
        payload_size = int(config.get('payload_size', 1))
        traffic_type = config.get('traffic_type', 'http')
        delay = int(config.get('delay', 0))
        paths = config.get('paths', '/').strip().split('\n')
        paths = [p.strip() for p in paths if p.strip()] or ['/']

        if not target_ip:
            self.is_running = False
            return False, 'Target IP is required'

        for i in range(num_threads):
            if traffic_type == 'http':
                t = threading.Thread(
                    target=self._worker_http,
                    args=(target_ip, port, method, duration, payload_size, paths, delay),
                    daemon=True
                )
            else:
                t = threading.Thread(
                    target=self._worker_tcp,
                    args=(target_ip, port, duration, payload_size, delay),
                    daemon=True
                )
            t.start()
            self.threads.append(t)

        def monitor():
            for t in self.threads:
                t.join()
            self.is_running = False

        threading.Thread(target=monitor, daemon=True).start()

        return True, f'Started {num_threads} threads targeting {target_ip}:{port}'

    def stop(self):
        if not self.is_running:
            return False, 'No traffic generation is running'
        self._stop_event.set()
        self.is_running = False
        return True, 'Stopping traffic generation...'

    def get_stats(self):
        stats = self.stats.to_dict()
        stats['is_running'] = self.is_running
        return stats
