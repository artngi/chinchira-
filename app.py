
import os
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import random

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

players = {}  # sid: {id, name, xp, room, match_id}
matches = {}  # match_id: { p1, p2, attacker, defender, p1_hp, p2_hp, current_attack, turn_count }

@app.route('/')
def index():
    return "Chinchilla Samurai Online Server is Running."

@socketio.on('register_player')
def handle_register(data):
    players[request.sid] = {
        'id': request.sid,
        'name': data.get('name', 'プレイヤー'),
        'xp': data.get('xp', 100),
        'match_id': None
    }
    broadcast_player_list()

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in players:
        match_id = players[sid].get('match_id')
        if match_id and match_id in matches:
            # 相手に切断を通知
            emit('opponent_disconnected', room=match_id, include_self=False)
            del matches[match_id]
        del players[sid]
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    broadcast_player_list()

def broadcast_player_list():
    active_players = [p for p in players.values() if p.get('match_id') is None]
    socketio.emit('player_list_update', active_players)

waiting_queue = []

@socketio.on('send_challenge')
def handle_challenge(data):
    target_id = data.get('target_id')
    match_id = str(uuid.uuid4())
    if target_id in players:
        socketio.emit('challenge_received', {
            'match_id': match_id,
            'challenger_id': request.sid,
            'challenger_name': data.get('name'),
            'challenger_xp': data.get('xp')
        }, room=target_id)

@socketio.on('accept_challenge')
def handle_accept(data):
    match_id = data.get('match_id')
    challenger_id = data.get('challenger_id')
    p1 = challenger_id
    p2 = request.sid
    
    if p1 in players and p2 in players:
        init_match(match_id, p1, p2)

@socketio.on('reject_challenge')
def handle_reject(data):
    challenger_id = data.get('challenger_id')
    if challenger_id in players:
        socketio.emit('challenge_rejected', room=challenger_id)

@socketio.on('start_random_match')
def handle_random_match(data):
    sid = request.sid
    if sid not in waiting_queue:
        waiting_queue.append(sid)
    
    if len(waiting_queue) >= 2:
        p1 = waiting_queue.pop(0)
        p2 = waiting_queue.pop(0)
        match_id = str(uuid.uuid4())
        init_match(match_id, p1, p2)

def init_match(match_id, p1, p2):
    join_room(match_id, sid=p1)
    join_room(match_id, sid=p2)
    
    players[p1]['match_id'] = match_id
    players[p2]['match_id'] = match_id
    
    # 割り当て（ランダムで先攻決定）
    p1_first = random.choice([True, False])
    attacker = p1 if p1_first else p2
    defender = p2 if p1_first else p1

    matches[match_id] = {
        'p1': p1,
        'p2': p2,
        'hp': { p1: 3, p2: 3 },
        'attacker': attacker,
        'defender': defender,
        'current_attack': None,
        'turn_count': 1
    }

    socketio.emit('start_online_battle', {
        'match_id': match_id,
        'opponent_name': players[p2]['name'],
        'role': 'attacker' if p1 == attacker else 'defender',
        'my_id': p1
    }, room=p1)

    socketio.emit('start_online_battle', {
        'match_id': match_id,
        'opponent_name': players[p1]['name'],
        'role': 'attacker' if p2 == attacker else 'defender',
        'my_id': p2
    }, room=p2)

    broadcast_player_list()

    # ゲーム開始の第一ターン要求
    socketio.emit('next_turn', {
        'attacker_id': attacker,
        'defender_id': defender,
        'turn_count': 1
    }, room=match_id)

@socketio.on('online_attack')
def handle_online_attack(data):
    match_id = data.get('match_id')
    attack_id = data.get('attack_id')
    
    if match_id in matches:
        match = matches[match_id]
        if request.sid == match['attacker']:
            match['current_attack'] = attack_id
            # 防御側に攻撃情報を送信
            emit('opponent_attacked', {
                'attack_id': attack_id,
                'attacker_id': request.sid
            }, room=match_id)

@socketio.on('online_defend_result')
def handle_online_defend_result(data):
    match_id = data.get('match_id')
    success = data.get('success')
    defend_id = data.get('defend_id')
    
    if match_id in matches:
        match = matches[match_id]
        if request.sid == match['defender']:
            attacker = match['attacker']
            defender = match['defender']

            if not success:
                match['hp'][defender] -= 1

            # 結果を双方にブロードキャスト
            emit('turn_result', {
                'attacker_id': attacker,
                'defender_id': defender,
                'attack_id': match['current_attack'],
                'defend_id': defend_id,
                'success': success,
                'p1_id': match['p1'],
                'p2_id': match['p2'],
                'hp': match['hp']
            }, room=match_id)

            # 勝敗判定
            if match['hp'][defender] <= 0:
                emit('match_over', {
                    'winner_id': attacker,
                    'loser_id': defender
                }, room=match_id)
                # ルーム整理
                players[match['p1']]['match_id'] = None
                players[match['p2']]['match_id'] = None
                del matches[match_id]
                broadcast_player_list()
            else:
                # 攻守交替して次ターンへ
                match['attacker'], match['defender'] = match['defender'], match['attacker']
                match['turn_count'] += 1
                match['current_attack'] = None

                socketio.emit('next_turn', {
                    'attacker_id': match['attacker'],
                    'defender_id': match['defender'],
                    'turn_count': match['turn_count']
                }, room=match_id)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
