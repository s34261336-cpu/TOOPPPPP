import hashlib, hmac, os, sqlite3, random, string, threading, time, secrets, requests
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.secret_key = (
    os.environ.get("SESSION_SECRET")
    or os.environ.get("FLASK_SECRET_KEY")
    or secrets.token_hex(32)
)
CORS(app)

BOT_TOKEN = (
    os.environ.get("BOT_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TOKEN")
    or ""
).strip()
ADMIN_CODE = os.environ.get("ADMIN_CODE", "").strip()
DB_PATH = os.path.join(BASE_DIR, os.environ.get("DB_PATH", "database.db"))
ENABLE_BOT_POLLING = os.environ.get("ENABLE_BOT_POLLING", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
ENABLE_CODE_SYNC = os.environ.get("ENABLE_CODE_SYNC", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
REPLIT_DEV_DOMAIN = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
APP_URL = (
    os.environ.get("WEBAPP_URL")
    or os.environ.get("WEB_APP_URL")
    or os.environ.get("MINI_APP_URL")
    or os.environ.get("APP_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or (
        f"https://{REPLIT_DEV_DOMAIN}"
        if ENABLE_BOT_POLLING and REPLIT_DEV_DOMAIN
        else ""
    )
    or ""
).strip()
CODE_SYNC_URL = (
    os.environ.get("CODE_SYNC_URL") or APP_URL
).strip().rstrip("/")
CODE_SYNC_SECRET = os.environ.get("CODE_SYNC_SECRET", "").strip()
CODE_SYNC_CONNECT_TIMEOUT = 5
CODE_SYNC_READ_TIMEOUT = 30
PREMIUM_PRICE = 50
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def roll_rarity():
    r = random.randint(1, 100)
    if r <= 10:
        return "Legendary", "#FFD700"
    if r <= 30:
        return "Mythic", "#FF6EF7"
    if r <= 60:
        return "Epic", "#A855F7"
    return "Common", "#94A3B8"


def allowed_file(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file, prefix=""):
    if not file or not allowed_file(file.filename):
        return None
    ext = file.filename.rsplit(".", 1)[1].lower()
    name = (
        prefix
        + "_"
        + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        + "."
        + ext
    )
    file.save(os.path.join(UPLOAD_FOLDER, name))
    return name


def nc(resp):
    resp.headers["Cache-Control"] = "no-store,no-cache,must-revalidate,max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE, username TEXT, first_name TEXT,
        stars INTEGER DEFAULT 0, is_premium INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    for col in [("is_premium", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
        except:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS codes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT, code TEXT UNIQUE, used INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS gifts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, price INTEGER DEFAULT 0,
        image TEXT DEFAULT NULL, in_shop INTEGER DEFAULT 1,
        quantity INTEGER DEFAULT NULL, sold INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    for col, typ in [
        ("image", "TEXT DEFAULT NULL"),
        ("in_shop", "INTEGER DEFAULT 1"),
        ("quantity", "INTEGER DEFAULT NULL"),
        ("sold", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE gifts ADD COLUMN {col} {typ}")
        except:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS user_gifts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, gift_id INTEGER,
        obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS gift_upgrades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gift_id INTEGER NOT NULL, name TEXT NOT NULL,
        counter INTEGER DEFAULT 0)""")
    try:
        c.execute("ALTER TABLE gift_upgrades ADD COLUMN counter INTEGER DEFAULT 0")
    except:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS upgrade_photos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        upgrade_id INTEGER NOT NULL, filename TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS upgrade_models(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        upgrade_id INTEGER NOT NULL, name TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_gift_upgrades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_gift_id INTEGER NOT NULL, upgrade_id INTEGER NOT NULL,
        rarity TEXT, rarity_color TEXT, number INTEGER,
        photo_filename TEXT, model_name TEXT,
        upgraded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    # Marketplace
    c.execute("""CREATE TABLE IF NOT EXISTS marketplace(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_gift_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    # Auctions
    c.execute("""CREATE TABLE IF NOT EXISTS auctions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_gift_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        start_price INTEGER NOT NULL,
        current_price INTEGER NOT NULL,
        current_bidder_id INTEGER DEFAULT NULL,
        end_time TIMESTAMP NOT NULL,
        status TEXT DEFAULT 'active')""")
    c.execute("""CREATE TABLE IF NOT EXISTS auction_bids(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        auction_id INTEGER NOT NULL,
        bidder_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        bid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()


def generate_code():
    return "".join(random.choices(string.digits, k=6))


def sync_code_to_webapp(telegram_id, code, username, first_name):
    if not ENABLE_CODE_SYNC or not CODE_SYNC_URL:
        return True
    if not CODE_SYNC_SECRET:
        app.logger.error("CODE_SYNC_URL задан, но CODE_SYNC_SECRET не задан")
        return False

    timestamp = int(time.time())
    signing_text = f"{telegram_id}:{code}:{timestamp}".encode()
    signature = hmac.new(
        CODE_SYNC_SECRET.encode(), signing_text, hashlib.sha256
    ).hexdigest()
    payload = {
        "telegram_id": telegram_id,
        "code": code,
        "username": username,
        "first_name": first_name,
        "timestamp": timestamp,
        "signature": signature,
    }
    endpoint = f"{CODE_SYNC_URL}/api/internal/sync-code"

    for attempt in range(3):
        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=(CODE_SYNC_CONNECT_TIMEOUT, CODE_SYNC_READ_TIMEOUT),
            )
            if response.ok and response.json().get("success"):
                return True
            if 400 <= response.status_code < 500:
                app.logger.error(
                    "Синхронизация кода отклонена: HTTP %s", response.status_code
                )
                return False
            app.logger.warning(
                "Синхронизация кода отклонена: HTTP %s", response.status_code
            )
        except requests.RequestException as exc:
            app.logger.warning("Ошибка синхронизации кода (попытка %s): %s", attempt + 1, exc)
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    return False


last_update_id = 0
_workers_started = False
_workers_lock = threading.Lock()


def poll_bot():
    global last_update_id
    if not BOT_TOKEN:
        print("BOT_TOKEN не задан — Telegram polling отключён.", flush=True)
        return

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35,
            )
            if resp.status_code == 200:
                for upd in resp.json().get("result", []):
                    last_update_id = upd["update_id"]
                    msg = upd.get("message")
                    if msg:
                        cid = str(msg["chat"]["id"])
                        fn = msg["from"].get("first_name", "Пользователь")
                        un = msg["from"].get("username", "")
                        conn = get_db()
                        c = conn.cursor()
                        c.execute(
                            "INSERT OR IGNORE INTO users(telegram_id,username,first_name) VALUES(?,?,?)",
                            (cid, un, fn),
                        )
                        conn.commit()
                        code = generate_code()
                        c.execute(
                            "DELETE FROM codes WHERE telegram_id=? AND used=0", (cid,)
                        )
                        c.execute(
                            "INSERT INTO codes(telegram_id,code) VALUES(?,?)",
                            (cid, code),
                        )
                        conn.commit()
                        conn.close()
                        if not sync_code_to_webapp(cid, code, un, fn):
                            app.logger.error(
                                "Код для Telegram ID %s не синхронизирован с Mini App",
                                cid,
                            )
                        kb = (
                            {
                                "inline_keyboard": [
                                    [
                                        {
                                            "text": "🌟 Открыть MiniApp",
                                            "web_app": {"url": APP_URL},
                                        }
                                    ]
                                ]
                            }
                            if APP_URL
                            else None
                        )
                        payload = {
                            "chat_id": cid,
                            "text": f"👋 Привет, {fn}!\n\n🔑 Код для входа:\n\n<code>{code}</code>\n\n⏳ Одноразовый!",
                            "parse_mode": "HTML",
                        }
                        if kb:
                            payload["reply_markup"] = kb
                        requests.post(
                            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                            json=payload,
                            timeout=5,
                        )
        except:
            time.sleep(5)
        time.sleep(1)


def process_auctions():
    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "SELECT * FROM auctions WHERE status='active' AND end_time<=datetime('now')"
            )
            ended = c.fetchall()
            for auc in ended:
                if auc["current_bidder_id"]:
                    # Transfer gift to winner
                    c.execute(
                        "UPDATE user_gifts SET user_id=? WHERE id=?",
                        (auc["current_bidder_id"], auc["user_gift_id"]),
                    )
                    # Deduct stars from winner
                    c.execute(
                        "UPDATE users SET stars=stars-? WHERE id=?",
                        (auc["current_price"], auc["current_bidder_id"]),
                    )
                    # Credit seller
                    c.execute(
                        "UPDATE users SET stars=stars+? WHERE id=?",
                        (auc["current_price"], auc["seller_id"]),
                    )
                    c.execute(
                        "UPDATE auctions SET status='sold' WHERE id=?", (auc["id"],)
                    )
                else:
                    c.execute(
                        "UPDATE auctions SET status='ended' WHERE id=?", (auc["id"],)
                    )
            conn.commit()
            conn.close()
        except:
            pass
        time.sleep(15)


def start_background_workers():
    global _workers_started
    with _workers_lock:
        if _workers_started:
            return
        init_db()
        if BOT_TOKEN and ENABLE_BOT_POLLING:
            threading.Thread(target=poll_bot, daemon=True).start()
        _workers_started = True


# ── AUTH ─────────────────────────────────────────────
@app.route("/")
def index():
    bot_username = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
    return render_template(
        "index.html",
        bot_username=bot_username,
        bot_link=f"https://t.me/{bot_username}" if bot_username else None,
    )


@app.route("/static/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/api/internal/sync-code", methods=["POST"])
def sync_code():
    if not CODE_SYNC_SECRET:
        return nc(jsonify({"success": False, "message": "Синхронизация не настроена"})), 503

    data = request.get_json(silent=True) or {}
    telegram_id = str(data.get("telegram_id", "")).strip()
    code = str(data.get("code", "")).strip()
    username = str(data.get("username", "")).strip()
    first_name = str(data.get("first_name", "Пользователь")).strip() or "Пользователь"
    try:
        timestamp = int(data.get("timestamp", 0))
    except (TypeError, ValueError):
        timestamp = 0
    signature = str(data.get("signature", "")).strip()

    if (
        not telegram_id
        or len(code) != 6
        or not code.isdigit()
        or not signature
        or abs(int(time.time()) - timestamp) > 120
    ):
        return nc(jsonify({"success": False, "message": "Некорректный запрос"})), 400

    signing_text = f"{telegram_id}:{code}:{timestamp}".encode()
    expected_signature = hmac.new(
        CODE_SYNC_SECRET.encode(), signing_text, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return nc(jsonify({"success": False, "message": "Недействительная подпись"})), 401

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users(telegram_id,username,first_name) VALUES(?,?,?)",
        (telegram_id, username, first_name),
    )
    c.execute("DELETE FROM codes WHERE telegram_id=? AND used=0", (telegram_id,))
    c.execute(
        "INSERT INTO codes(telegram_id,code) VALUES(?,?)",
        (telegram_id, code),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    code = data.get("code", "").strip()
    if ADMIN_CODE and code == ADMIN_CODE:
        session["admin"] = True
        session["user_id"] = None
        return nc(jsonify({"success": True, "role": "admin"}))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE code=? AND used=0", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return nc(jsonify({"success": False, "message": "Неверный или устаревший код"}))
    tid = row["telegram_id"]
    c.execute("UPDATE codes SET used=1 WHERE code=?", (code,))
    conn.commit()
    c.execute("SELECT * FROM users WHERE telegram_id=?", (tid,))
    user = c.fetchone()
    conn.close()
    if user:
        session["user_id"] = user["id"]
        session["admin"] = False
        return nc(
            jsonify(
                {
                    "success": True,
                    "role": "user",
                    "user": {
                        "id": user["id"],
                        "first_name": user["first_name"],
                        "username": user["username"],
                        "stars": user["stars"],
                        "is_premium": bool(user["is_premium"]),
                    },
                }
            )
        )
    return nc(jsonify({"success": False, "message": "Пользователь не найден"}))


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return nc(jsonify({"success": True}))


# ── PROFILE ──────────────────────────────────────────
@app.route("/api/profile")
def profile():
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    if not user:
        conn.close()
        return nc(jsonify({"error": "Не найден"})), 401
    c.execute(
        """
        SELECT ug.id as ug_id, g.id as g_id, g.name, g.image,
               gu.id as upg_id,
               g.price, ugu.rarity, ugu.rarity_color, ugu.number, ugu.photo_filename, ugu.model_name,
               ml.id as market_id, ml.price as market_price
        FROM user_gifts ug
        INNER JOIN gifts g ON g.id=ug.gift_id
        LEFT JOIN gift_upgrades gu ON gu.gift_id=g.id
        LEFT JOIN user_gift_upgrades ugu ON ugu.user_gift_id=ug.id
        LEFT JOIN marketplace ml ON ml.user_gift_id=ug.id AND ml.status='active'
        WHERE ug.user_id=?
        ORDER BY ug.obtained_at DESC""",
        (uid,),
    )
    rows = c.fetchall()
    conn.close()
    gifts_map = {}
    for r in rows:
        key = r["ug_id"]
        if key not in gifts_map:
            gifts_map[key] = {
                "ug_id": r["ug_id"],
                "id": r["g_id"],
                "name": r["name"],
                "image": r["image"],
                "price": r["price"] or 0,
                "has_upgrade": r["upg_id"] is not None,
                "upgrade_result": None,
                "on_market": r["market_id"] is not None,
                "market_id": r["market_id"],
                "market_price": r["market_price"],
            }
        if r["upg_id"]:
            gifts_map[key]["has_upgrade"] = True
        if r["rarity"] and not gifts_map[key]["upgrade_result"]:
            gifts_map[key]["upgrade_result"] = {
                "rarity": r["rarity"],
                "rarity_color": r["rarity_color"],
                "number": r["number"],
                "photo": r["photo_filename"],
                "model": r["model_name"],
            }
    return nc(
        jsonify(
            {
                "id": user["id"],
                "first_name": user["first_name"],
                "username": user["username"],
                "stars": user["stars"],
                "is_premium": bool(user["is_premium"]),
                "gifts": list(gifts_map.values()),
                "premium_price": PREMIUM_PRICE,
            }
        )
    )


@app.route("/api/buy_premium", methods=["POST"])
def buy_premium():
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    if user["is_premium"]:
        conn.close()
        return nc(jsonify({"success": False, "message": "Уже есть Premium!"}))
    if user["stars"] < PREMIUM_PRICE:
        conn.close()
        return nc(jsonify({"success": False, "message": f"Нужно {PREMIUM_PRICE} ⭐"}))
    c.execute(
        "UPDATE users SET stars=stars-?,is_premium=1 WHERE id=?", (PREMIUM_PRICE, uid)
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


# ── SHOP ─────────────────────────────────────────────
@app.route("/api/shop")
def shop():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id,name,price,image,in_shop,quantity,sold FROM gifts WHERE in_shop=1 ORDER BY id ASC"
    )
    gifts = []
    for r in c.fetchall():
        g = dict(r)
        if g["quantity"] is not None:
            g["remaining"] = max(0, g["quantity"] - (g["sold"] or 0))
            g["sold_out"] = g["remaining"] <= 0
        else:
            g["remaining"] = None
            g["sold_out"] = False
        gifts.append(g)
    conn.close()
    return nc(jsonify(gifts))


@app.route("/api/shop/buy/<int:gid>", methods=["POST"])
def shop_buy(gid):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts WHERE id=? AND in_shop=1", (gid,))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок не найден"}))
    if gift["quantity"] is not None and (gift["quantity"] - (gift["sold"] or 0)) <= 0:
        conn.close()
        return nc(jsonify({"success": False, "message": "Sold Out!"}))
    c.execute("SELECT stars FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    if user["stars"] < gift["price"]:
        conn.close()
        return nc(jsonify({"success": False, "message": f"Нужно {gift['price']} ⭐"}))
    c.execute("UPDATE users SET stars=stars-? WHERE id=?", (gift["price"], uid))
    c.execute("INSERT INTO user_gifts(user_id,gift_id) VALUES(?,?)", (uid, gid))
    if gift["quantity"] is not None:
        c.execute("UPDATE gifts SET sold=sold+1 WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    return nc(
        jsonify({"success": True, "message": f"Подарок «{gift['name']}» получен!"})
    )


# ── UPGRADE ──────────────────────────────────────────
@app.route("/api/upgrade_options/<int:ug_id>")
def upgrade_options(ug_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT gu.id
           FROM gift_upgrades gu
           JOIN user_gifts ug ON ug.gift_id=gu.gift_id
           WHERE ug.id=? AND ug.user_id=?""",
        (ug_id, uid),
    )
    upg = c.fetchone()
    if not upg:
        conn.close()
        return nc(jsonify({"success": False, "message": "Улучшение недоступно"})), 404
    c.execute(
        "SELECT filename FROM upgrade_photos WHERE upgrade_id=? ORDER BY id",
        (upg["id"],),
    )
    photos = [r["filename"] for r in c.fetchall()]
    c.execute(
        "SELECT name FROM upgrade_models WHERE upgrade_id=? ORDER BY id",
        (upg["id"],),
    )
    models = [r["name"] for r in c.fetchall()]
    conn.close()
    return nc(jsonify({"photos": photos, "models": models}))


@app.route("/api/upgrade/<int:ug_id>", methods=["POST"])
def do_upgrade(ug_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id=? AND user_id=?", (ug_id, uid))
    ug = c.fetchone()
    if not ug:
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок не найден"}))
    c.execute("SELECT * FROM user_gift_upgrades WHERE user_gift_id=?", (ug_id,))
    if c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Уже улучшен!"}))
    c.execute("SELECT * FROM gift_upgrades WHERE gift_id=?", (ug["gift_id"],))
    upg = c.fetchone()
    if not upg:
        conn.close()
        return nc(jsonify({"success": False, "message": "Нет улучшений"}))
    c.execute("UPDATE gift_upgrades SET counter=counter+1 WHERE id=?", (upg["id"],))
    conn.commit()
    c.execute("SELECT counter FROM gift_upgrades WHERE id=?", (upg["id"],))
    number = c.fetchone()["counter"]
    rarity, rarity_color = roll_rarity()
    c.execute("SELECT filename FROM upgrade_photos WHERE upgrade_id=?", (upg["id"],))
    photos = [r["filename"] for r in c.fetchall()]
    photo = random.choice(photos) if photos else None
    c.execute("SELECT name FROM upgrade_models WHERE upgrade_id=?", (upg["id"],))
    models = [r["name"] for r in c.fetchall()]
    model = random.choice(models) if models else None
    c.execute(
        """INSERT INTO user_gift_upgrades
                 (user_gift_id,upgrade_id,rarity,rarity_color,number,photo_filename,model_name)
                 VALUES(?,?,?,?,?,?,?)""",
        (ug_id, upg["id"], rarity, rarity_color, number, photo, model),
    )
    conn.commit()
    conn.close()
    return nc(
        jsonify(
            {
                "success": True,
                "result": {
                    "rarity": rarity,
                    "rarity_color": rarity_color,
                    "number": number,
                    "photo": photo,
                    "model": model,
                    "bg_id": {"Common": 0, "Epic": 3, "Mythic": 5, "Legendary": 7}.get(
                        rarity, 0
                    ),
                },
            }
        )
    )


# ── GIFT TRANSFER ─────────────────────────────────────
@app.route("/api/gift/transfer", methods=["POST"])
def transfer_gift():
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    data = request.json or {}
    ug_id = data.get("user_gift_id")
    username = str(data.get("username", "")).strip().lstrip("@")
    if not ug_id or not username:
        return nc(jsonify({"success": False, "message": "Укажи получателя"}))
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM user_gifts WHERE id=? AND user_id=?",
        (ug_id, uid),
    )
    gift = c.fetchone()
    if not gift:
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок не найден"}))
    c.execute(
        "SELECT id FROM user_gift_upgrades WHERE user_gift_id=?",
        (ug_id,),
    )
    if not c.fetchone():
        conn.close()
        return nc(
            jsonify(
                {
                    "success": False,
                    "message": "Передать можно только улучшенный подарок",
                }
            )
        )
    c.execute(
        "SELECT id, first_name FROM users WHERE lower(username)=lower(?)",
        (username,),
    )
    recipient = c.fetchone()
    if not recipient:
        conn.close()
        return nc(jsonify({"success": False, "message": "Получатель не найден"}))
    if recipient["id"] == uid:
        conn.close()
        return nc(jsonify({"success": False, "message": "Нельзя передать себе"}))
    c.execute(
        "SELECT id FROM marketplace WHERE user_gift_id=? AND status='active'",
        (ug_id,),
    )
    if c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Сначала снимите подарок с продажи"}))
    c.execute("UPDATE user_gifts SET user_id=? WHERE id=?", (recipient["id"], ug_id))
    conn.commit()
    conn.close()
    return nc(
        jsonify(
            {
                "success": True,
                "message": f"Подарок передан пользователю @{username}",
            }
        )
    )


# ── MARKETPLACE ───────────────────────────────────────
@app.route("/api/market")
def market():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT ml.id, ml.price, ml.listed_at,
               ug.id as ug_id, g.name, g.image,
               u.first_name as seller_name,
               ugu.rarity, ugu.rarity_color, ugu.number, ugu.photo_filename, ugu.model_name
        FROM marketplace ml
        JOIN user_gifts ug ON ug.id=ml.user_gift_id
        JOIN gifts g ON g.id=ug.gift_id
        JOIN users u ON u.id=ml.seller_id
        JOIN user_gift_upgrades ugu ON ugu.user_gift_id=ml.user_gift_id
        WHERE ml.status='active'
        ORDER BY ml.listed_at DESC""")
    items = [dict(r) for r in c.fetchall()]
    conn.close()
    return nc(jsonify(items))


@app.route("/api/market/list", methods=["POST"])
def market_list():
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    data = request.json
    ug_id = data.get("user_gift_id")
    price = data.get("price", 0)
    if not ug_id or price < 1:
        return nc(jsonify({"success": False, "message": "Укажи цену"}))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id=? AND user_id=?", (ug_id, uid))
    ug = c.fetchone()
    if not ug:
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок не найден"}))
    c.execute("SELECT * FROM user_gift_upgrades WHERE user_gift_id=?", (ug_id,))
    if not c.fetchone():
        conn.close()
        return nc(
            jsonify(
                {
                    "success": False,
                    "message": "Можно продавать только улучшённые подарки!",
                }
            )
        )
    c.execute(
        "SELECT * FROM marketplace WHERE user_gift_id=? AND status='active'", (ug_id,)
    )
    if c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Уже на продаже"}))
    c.execute(
        "INSERT INTO marketplace(user_gift_id,seller_id,price) VALUES(?,?,?)",
        (ug_id, uid, price),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/market/buy/<int:listing_id>", methods=["POST"])
def market_buy(listing_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM marketplace WHERE id=? AND status='active'", (listing_id,))
    ml = c.fetchone()
    if not ml:
        conn.close()
        return nc(jsonify({"success": False, "message": "Лот не найден"}))
    if ml["seller_id"] == uid:
        conn.close()
        return nc(jsonify({"success": False, "message": "Нельзя купить свой лот"}))
    c.execute("SELECT stars FROM users WHERE id=?", (uid,))
    buyer = c.fetchone()
    if buyer["stars"] < ml["price"]:
        conn.close()
        return nc(jsonify({"success": False, "message": f"Нужно {ml['price']} ⭐"}))
    c.execute("UPDATE users SET stars=stars-? WHERE id=?", (ml["price"], uid))
    c.execute(
        "UPDATE users SET stars=stars+? WHERE id=?", (ml["price"], ml["seller_id"])
    )
    c.execute("UPDATE user_gifts SET user_id=? WHERE id=?", (uid, ml["user_gift_id"]))
    c.execute("UPDATE marketplace SET status='sold' WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/market/cancel/<int:listing_id>", methods=["POST"])
def market_cancel(listing_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM marketplace WHERE id=? AND seller_id=? AND status='active'",
        (listing_id, uid),
    )
    if not c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Лот не найден"}))
    c.execute("UPDATE marketplace SET status='cancelled' WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


# ── AUCTIONS ──────────────────────────────────────────
@app.route("/api/auctions")
def auctions():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT auc.id, auc.start_price, auc.current_price, auc.end_time, auc.status,
               auc.current_bidder_id,
               ug.id as ug_id, g.name, g.image,
               u.first_name as seller_name,
               ugu.rarity, ugu.rarity_color, ugu.number, ugu.photo_filename, ugu.model_name,
               (SELECT COUNT(*) FROM auction_bids WHERE auction_id=auc.id) as bid_count
        FROM auctions auc
        JOIN user_gifts ug ON ug.id=auc.user_gift_id
        JOIN gifts g ON g.id=ug.gift_id
        JOIN users u ON u.id=auc.seller_id
        JOIN user_gift_upgrades ugu ON ugu.user_gift_id=auc.user_gift_id
        WHERE auc.status='active'
        ORDER BY auc.end_time ASC""")
    items = [dict(r) for r in c.fetchall()]
    conn.close()
    return nc(jsonify(items))


@app.route("/api/auction/create", methods=["POST"])
def auction_create():
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    data = request.json
    ug_id = data.get("user_gift_id")
    start_price = data.get("start_price", 1)
    duration_hours = max(1, min(168, int(data.get("duration_hours", 24))))
    if not ug_id or start_price < 1:
        return nc(jsonify({"success": False, "message": "Укажи стартовую цену"}))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id=? AND user_id=?", (ug_id, uid))
    if not c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок не найден"}))
    c.execute("SELECT * FROM user_gift_upgrades WHERE user_gift_id=?", (ug_id,))
    if not c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Только улучшённые подарки!"}))
    c.execute(
        "SELECT * FROM marketplace WHERE user_gift_id=? AND status='active'", (ug_id,)
    )
    if c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Подарок на рынке"}))
    c.execute(
        "SELECT * FROM auctions WHERE user_gift_id=? AND status='active'", (ug_id,)
    )
    if c.fetchone():
        conn.close()
        return nc(jsonify({"success": False, "message": "Уже на аукционе"}))
    c.execute(
        """INSERT INTO auctions(user_gift_id,seller_id,start_price,current_price,end_time)
                 VALUES(?,?,?,?,datetime('now',?))""",
        (ug_id, uid, start_price, start_price, f"+{duration_hours} hours"),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/auction/bid/<int:auc_id>", methods=["POST"])
def auction_bid(auc_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    data = request.json
    amount = data.get("amount", 0)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (auc_id,))
    auc = c.fetchone()
    if not auc:
        conn.close()
        return nc(jsonify({"success": False, "message": "Аукцион не найден"}))
    if auc["seller_id"] == uid:
        conn.close()
        return nc(
            jsonify({"success": False, "message": "Нельзя ставить на свой аукцион"})
        )
    if amount <= auc["current_price"]:
        conn.close()
        return nc(
            jsonify(
                {
                    "success": False,
                    "message": f"Ставка должна быть больше {auc['current_price']} ⭐",
                }
            )
        )
    c.execute("SELECT stars FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    if user["stars"] < amount:
        conn.close()
        return nc(jsonify({"success": False, "message": "Недостаточно звёзд"}))
    c.execute(
        "UPDATE auctions SET current_price=?,current_bidder_id=? WHERE id=?",
        (amount, uid, auc_id),
    )
    c.execute(
        "INSERT INTO auction_bids(auction_id,bidder_id,amount) VALUES(?,?,?)",
        (auc_id, uid, amount),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/auction/cancel/<int:auc_id>", methods=["POST"])
def auction_cancel(auc_id):
    uid = session.get("user_id")
    if not uid:
        return nc(jsonify({"error": "Не авторизован"})), 401
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM auctions WHERE id=? AND seller_id=? AND status='active'",
        (auc_id, uid),
    )
    auc = c.fetchone()
    if not auc:
        conn.close()
        return nc(jsonify({"success": False, "message": "Не найден"}))
    if auc["current_bidder_id"]:
        conn.close()
        return nc(
            jsonify({"success": False, "message": "Уже есть ставки, нельзя отменить"})
        )
    c.execute("UPDATE auctions SET status='cancelled' WHERE id=?", (auc_id,))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


# ── ADMIN: GIFTS ──────────────────────────────────────
@app.route("/api/admin/gifts")
def get_gifts():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id,name,price,image,in_shop,quantity,sold FROM gifts ORDER BY id DESC"
    )
    gifts = [dict(r) for r in c.fetchall()]
    conn.close()
    return nc(jsonify(gifts))


@app.route("/api/admin/gifts", methods=["POST"])
def add_gift():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    name = request.form.get("name", "").strip()
    if not name:
        return jsonify({"error": "Нет названия"}), 400
    price = int(request.form.get("price", 0) or 0)
    in_shop = 1 if request.form.get("in_shop", "1") == "1" else 0
    qty_raw = request.form.get("quantity", "").strip()
    quantity = int(qty_raw) if qty_raw else None
    image = None
    if "image" in request.files:
        image = save_upload(request.files["image"], "gift")
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO gifts(name,price,image,in_shop,quantity,sold) VALUES(?,?,?,?,?,0)",
        (name, price, image, in_shop, quantity),
    )
    conn.commit()
    gid = c.lastrowid
    conn.close()
    return nc(jsonify({"success": True, "id": gid}))


@app.route("/api/admin/gifts/<int:gid>", methods=["DELETE"])
def delete_gift(gid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM gifts WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


# ── ADMIN: UPGRADES ───────────────────────────────────
@app.route("/api/admin/upgrades")
def get_upgrades():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT gu.*,g.name as gift_name,
                        COUNT(DISTINCT up.id) as photo_count,
                        COUNT(DISTINCT um.id) as model_count
                 FROM gift_upgrades gu JOIN gifts g ON g.id=gu.gift_id
                 LEFT JOIN upgrade_photos up ON up.upgrade_id=gu.id
                 LEFT JOIN upgrade_models um ON um.upgrade_id=gu.id
                 GROUP BY gu.id ORDER BY gu.id DESC""")
    upgrades = [dict(r) for r in c.fetchall()]
    for u in upgrades:
        c.execute("SELECT filename FROM upgrade_photos WHERE upgrade_id=?", (u["id"],))
        u["photos"] = [r["filename"] for r in c.fetchall()]
        c.execute("SELECT name FROM upgrade_models WHERE upgrade_id=?", (u["id"],))
        u["models"] = [r["name"] for r in c.fetchall()]
    conn.close()
    return nc(jsonify(upgrades))


@app.route("/api/admin/upgrades", methods=["POST"])
def create_upgrade():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    data = request.json
    gid = data.get("gift_id")
    name = data.get("name", "").strip()
    if not gid or not name:
        return jsonify({"error": "Неверные данные"}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO gift_upgrades(gift_id,name,counter) VALUES(?,?,0)", (gid, name)
    )
    conn.commit()
    uid = c.lastrowid
    for m in data.get("models", []):
        if m.strip():
            c.execute(
                "INSERT INTO upgrade_models(upgrade_id,name) VALUES(?,?)",
                (uid, m.strip()),
            )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True, "id": uid}))


@app.route("/api/admin/upgrades/<int:uid>/photos", methods=["POST"])
def add_upgrade_photos(uid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM upgrade_photos WHERE upgrade_id=?", (uid,))
    existing = c.fetchone()["cnt"]
    saved = []
    for f in request.files.getlist("photos"):
        if existing + len(saved) >= 15:
            break
        fn = save_upload(f, f"upg{uid}")
        if fn:
            c.execute(
                "INSERT INTO upgrade_photos(upgrade_id,filename) VALUES(?,?)", (uid, fn)
            )
            saved.append(fn)
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True, "saved": len(saved)}))


@app.route("/api/admin/upgrades/<int:uid>/models", methods=["POST"])
def add_upgrade_model(uid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    name = request.json.get("name", "").strip()
    if not name:
        return jsonify({"error": "Нет названия"}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO upgrade_models(upgrade_id,name) VALUES(?,?)", (uid, name))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/upgrades/<int:uid>/photos/<int:pid>", methods=["DELETE"])
def delete_upgrade_photo(uid, pid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT filename FROM upgrade_photos WHERE id=? AND upgrade_id=?", (pid, uid)
    )
    row = c.fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, row["filename"]))
        except:
            pass
        c.execute("DELETE FROM upgrade_photos WHERE id=?", (pid,))
        conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/upgrades/<int:uid>/models/<int:mid>", methods=["DELETE"])
def delete_upgrade_model(uid, mid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM upgrade_models WHERE id=? AND upgrade_id=?", (mid, uid))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/upgrades/<int:uid>", methods=["DELETE"])
def delete_upgrade(uid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT filename FROM upgrade_photos WHERE upgrade_id=?", (uid,))
    for r in c.fetchall():
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, r["filename"]))
        except:
            pass
    c.execute("DELETE FROM upgrade_photos WHERE upgrade_id=?", (uid,))
    c.execute("DELETE FROM upgrade_models WHERE upgrade_id=?", (uid,))
    c.execute("DELETE FROM gift_upgrades WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/upgrade_photos_list/<int:uid>")
def upgrade_photos_list(uid):
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id,filename FROM upgrade_photos WHERE upgrade_id=?", (uid,))
    photos = [dict(r) for r in c.fetchall()]
    c.execute("SELECT id,name FROM upgrade_models WHERE upgrade_id=?", (uid,))
    models = [dict(r) for r in c.fetchall()]
    conn.close()
    return nc(jsonify({"photos": photos, "models": models}))


# ── ADMIN: USERS ──────────────────────────────────────
@app.route("/api/admin/users")
def get_users():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id,telegram_id,username,first_name,stars,is_premium FROM users")
    users = [dict(r) for r in c.fetchall()]
    conn.close()
    return nc(jsonify(users))


@app.route("/api/admin/give_stars", methods=["POST"])
def give_stars():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET stars=stars+? WHERE id=?",
        (data.get("stars", 0), data.get("user_id")),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/give_gift", methods=["POST"])
def give_gift():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_gifts(user_id,gift_id) VALUES(?,?)",
        (data.get("user_id"), data.get("gift_id")),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


@app.route("/api/admin/set_premium", methods=["POST"])
def set_premium():
    if not session.get("admin"):
        return jsonify({"error": "Нет доступа"}), 403
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET is_premium=? WHERE id=?",
        (1 if data.get("premium") else 0, data.get("user_id")),
    )
    conn.commit()
    conn.close()
    return nc(jsonify({"success": True}))


start_background_workers()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
