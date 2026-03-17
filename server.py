from flask import Flask, jsonify, request
from flask_cors import CORS
from instagrapi import Client
from instagrapi.exceptions import LoginRequired
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
import random
import uuid
import os
import json

app = Flask(__name__)
CORS(app)

# Firebase Init — Environment Variable Se
firebase_key = json.loads(os.environ.get('FIREBASE_KEY_JSON', '{}'))
cred = credentials.Certificate(firebase_key)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://topcoin-follow-default-rtdb.asia-southeast1.firebasedatabase.app'
})

DEVICES = [
    {
        "app_version": "269.0.0.18.75",
        "android_version": 26,
        "android_release": "8.0.0",
        "dpi": "480dpi",
        "resolution": "1080x1920",
        "manufacturer": "OnePlus",
        "device": "OnePlus5",
        "model": "ONEPLUS A5000",
        "cpu": "qcom",
    },
    {
        "app_version": "269.0.0.18.75",
        "android_version": 28,
        "android_release": "9.0.0",
        "dpi": "560dpi",
        "resolution": "1440x2960",
        "manufacturer": "samsung",
        "device": "star2qltecs",
        "model": "SM-G965F",
        "cpu": "samsungexynos9810",
    }
]

users = {}

class MiningSession:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.cl = Client()
        self.cl.set_device(random.choice(DEVICES))
        self.is_mining = False
        self.followed_count = 0
        self.coins = 0
        self.is_logged_in = False

    def login(self):
        try:
            try:
                self.cl.load_settings(f"{self.username}_session.json")
                self.cl.login(self.username, self.password)
            except:
                self.cl.login(self.username, self.password)
                self.cl.dump_settings(f"{self.username}_session.json")
            self.is_logged_in = True
            user_ref = db.reference(f'users/{self.username}')
            user_data = user_ref.get()
            if user_data:
                self.coins = user_data.get('coins', 0)
            return True
        except Exception as e:
            print(f"Login Error: {e}")
            return False

    def safe_follow(self, target):
        if not self.is_mining:
            return "stopped"
        try:
            user_info = self.cl.user_info_by_username(target)
            if user_info.is_private:
                return "skip"
            friendship = self.cl.user_friendship_v1(user_info.pk)
            if friendship.following:
                return "already"
            self.cl.user_follow(user_info.pk)
            return "followed"
        except LoginRequired:
            self.login()
            return self.safe_follow(target)
        except Exception as e:
            print(f"Error: {e}")
            return "error"

    def get_next_order(self):
        try:
            orders_ref = db.reference('orders')
            orders = orders_ref.order_by_child('status').equal_to('active').get()
            if not orders:
                return None
            for order_id, order in orders.items():
                target = order.get('target')
                followers_done = order.get('followers_done', [])
                if isinstance(followers_done, dict):
                    followers_done = list(followers_done.values())
                if self.username not in followers_done:
                    return {
                        'order_id': order_id,
                        'target': target,
                        'total': order.get('total', 10),
                        'completed': order.get('completed', 0)
                    }
            return None
        except Exception as e:
            print(f"Get order error: {e}")
            return None

    def update_order(self, order_id):
        try:
            order_ref = db.reference(f'orders/{order_id}')
            order = order_ref.get()
            if not order:
                return
            completed = order.get('completed', 0) + 1
            total = order.get('total', 10)
            followers_done = order.get('followers_done', [])
            if isinstance(followers_done, dict):
                followers_done = list(followers_done.values())
            followers_done.append(self.username)
            update_data = {
                'completed': completed,
                'followers_done': followers_done
            }
            if completed >= total:
                update_data['status'] = 'completed'
            order_ref.update(update_data)
        except Exception as e:
            print(f"Update order error: {e}")

    def update_coins_firebase(self):
        try:
            user_ref = db.reference(f'users/{self.username}')
            user_ref.update({'coins': self.coins})
        except Exception as e:
            print(f"Update coins error: {e}")

    def mining_loop(self):
        print(f"Mining started for {self.username}")
        while self.is_mining:
            order = self.get_next_order()
            if order:
                target = order['target']
                order_id = order['order_id']
                result = self.safe_follow(target)
                if result == "followed":
                    self.followed_count += 1
                    self.coins += 4
                    self.update_order(order_id)
                    self.update_coins_firebase()
                    print(f"{self.username} followed {target} | +4 coins | Total: {self.coins}")
                    time.sleep(random.uniform(4, 8))
                    if self.followed_count % 100 == 0:
                        print("100 follows! 1 hour break...")
                        for i in range(3600, 0, -60):
                            if not self.is_mining:
                                return
                            time.sleep(60)
                elif result == "already":
                    print(f"Already followed {target} - 0 coins")
                elif result == "skip":
                    print(f"Private {target} - 0 coins")
                elif result == "stopped":
                    return
                elif result == "error":
                    time.sleep(5)
            else:
                print("No active orders - waiting...")
                time.sleep(10)


@app.route('/')
def home():
    return jsonify({
        'status': 'success',
        'message': 'FollowHub Server Running!'
    })


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({
            'status': 'error',
            'message': 'Username aur password daalo!'
        })
    if username in users:
        return jsonify({
            'status': 'success',
            'message': 'Already logged in!',
            'username': username,
            'coins': users[username].coins
        })
    session = MiningSession(username, password)
    success = session.login()
    if success:
        users[username] = session
        return jsonify({
            'status': 'success',
            'message': 'Login successful!',
            'username': username,
            'coins': session.coins
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Login failed!'
        })


@app.route('/api/start_mining', methods=['POST'])
def start_mining():
    data = request.json
    username = data.get('username')
    if username not in users:
        return jsonify({
            'status': 'error',
            'message': 'User not logged in!'
        })
    session = users[username]
    if session.is_mining:
        return jsonify({
            'status': 'success',
            'message': 'Mining already running!'
        })
    session.is_mining = True
    t = threading.Thread(target=session.mining_loop)
    t.daemon = True
    t.start()
    return jsonify({
        'status': 'success',
        'message': 'Mining started!'
    })


@app.route('/api/stop_mining', methods=['POST'])
def stop_mining():
    data = request.json
    username = data.get('username')
    if username not in users:
        return jsonify({
            'status': 'error',
            'message': 'User not logged in!'
        })
    users[username].is_mining = False
    return jsonify({
        'status': 'success',
        'message': 'Mining stopped!'
    })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    username = request.args.get('username')
    if username not in users:
        return jsonify({
            'status': 'error',
            'message': 'User not found!'
        })
    session = users[username]
    return jsonify({
        'status': 'success',
        'username': username,
        'coins': session.coins,
        'followed_count': session.followed_count,
        'is_mining': session.is_mining
    })


@app.route('/api/place_order', methods=['POST'])
def place_order():
    data = request.json
    username = data.get('username')
    target = data.get('target')
    quantity = data.get('quantity', 10)
    use_gems = data.get('use_gems', False)
    if username not in users:
        return jsonify({
            'status': 'error',
            'message': 'User not logged in!'
        })
    session = users[username]
    coins_needed = quantity * 8
    if not use_gems:
        if session.coins < coins_needed:
            return jsonify({
                'status': 'error',
                'message': f'{coins_needed} coins chahiye! Tumhare paas {session.coins} hain.'
            })
        session.coins -= coins_needed
        session.update_coins_firebase()
    order_id = str(uuid.uuid4())[:8]
    orders_ref = db.reference(f'orders/{order_id}')
    orders_ref.set({
        'target': target,
        'owner': username,
        'total': quantity,
        'completed': 0,
        'status': 'active',
        'followers_done': [],
        'created_at': time.time()
    })
    return jsonify({
        'status': 'success',
        'message': f'{quantity} followers order placed!',
        'order_id': order_id,
        'remaining_coins': session.coins
    })


@app.route('/api/orders', methods=['GET'])
def get_orders():
    username = request.args.get('username')
    try:
        orders_ref = db.reference('orders')
        all_orders = orders_ref.order_by_child('owner').equal_to(username).get()
        if not all_orders:
            return jsonify({
                'status': 'success',
                'orders': []
            })
        orders_list = []
        for order_id, order in all_orders.items():
            orders_list.append({
                'order_id': order_id,
                'target': order.get('target'),
                'total': order.get('total'),
                'completed': order.get('completed'),
                'status': order.get('status')
            })
        return jsonify({
            'status': 'success',
            'orders': orders_list
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )