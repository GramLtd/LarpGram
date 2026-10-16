import asyncio, hashlib, hmac, io, json, math, os, random, secrets, sqlite3, time, urllib.parse, urllib.request
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle,
                           InputTextMessageContent, LabeledPrice, WebAppInfo)
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFilter, ImageFont

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"].rstrip("/")
ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
FREE_COOLDOWN = 24 * 3600
FRIENDS_REQUIRED = 5
REF_BONUS = 5      # ⭐ пригласившему за нового друга
REF_PERCENT = 10   # % от трат друга на кейсы
MAX_MULTI = 5      # сколько платных кейсов можно открыть за раз
STORY_MIN_DELAY = 20  # сек между нажатием "в сторис" и выводом
CASE_RTP = 0.85    # средний возврат платного кейса (доля цены)
ECONOMY_VERSION = "3"  # поменяйте, чтобы при старте пересобрать кейсы и призы (правки в админке сбросятся)
SELL_RATE = 0.9    # продажа подарка из инвентаря: доля оценки на баланс
MINES_EDGE = 0.96  # множитель мин = EDGE * честный коэффициент
MINES_MAX_WIN = 181818  # максимум выплаты за раунд мин, ⭐
UPGRADE_EDGE = 0.9  # шанс апгрейда = стоимость источника / стоимость цели * EDGE
UPGRADE_MAX_CHANCE = 0.8
CELLS = 25
TOPUP_MIN, TOPUP_MAX = 50, 10000  # пополнение на любую сумму в этих пределах, ⭐
PLINKO_RTP = 0.95  # средний возврат плинко
PLINKO_MAX_BET = 10000

bot = Bot(TOKEN)
dp = Dispatcher()
BOT_USERNAME = ""

# ---------- каталог NFT ----------
# static/gifts.json: все NFT-подарки Telegram и их модели с редкостью (обновить: python tools/fetch_gifts.py).
# Данные и картинки моделей: api.changes.tg / cdn.changes.tg. Условие API: видимая благодарность в приложении (строка в профиле).
CATALOG = {g["name"]: g for g in json.load(open("static/gifts.json", encoding="utf-8"))}
TON_STARS = 69  # ⭐ за 1 TON, поменяйте под курс
# Floor коллекций в TON (примерно, по маркетплейсам). Не указан — DEFAULT_FLOOR. Правьте под рынок и перезапускайте.
DEFAULT_FLOOR = 4.5
FLOORS = {
    "Plush Pepe": 5000, "Heart Locket": 1500, "Durov's Cap": 390, "Precious Peach": 245, "Heroic Helmet": 175, "Resistance Dog": 710,
    "Astral Shard": 114, "Mighty Arm": 120, "Loot Bag": 55, "Nail Bracelet": 60, "Ion Gem": 50, "Mini Oscar": 50, "Perfume Bottle": 45,
    "Gem Signet": 45, "Khabib's Papakha": 40, "Magic Potion": 30, "Genie Lamp": 30, "Scared Cat": 30, "Sharp Tongue": 15, "Swiss Watch": 20,
    "Signet Ring": 20, "Kissed Frog": 20, "Bonded Ring": 30, "Vintage Cigar": 36, "Voodoo Doll": 35, "Eternal Rose": 15,
    "Neko Helmet": 15, "Toy Bear": 15, "Electric Skull": 15, "Low Rider": 25, "Snoop Cigar": 8, "Durov's Glasses": 20,
    "Diamond Ring": 10, "Love Potion": 8, "Record Player": 8, "Trapped Heart": 8, "Skull Flower": 7, "Top Hat": 7, "Mad Pumpkin": 8,
    "Rare Bird": 12, "Bow Tie": 5, "Sakura Flower": 5, "Berry Box": 5, "Bunny Muffin": 5, "Crystal Ball": 6, "Flying Broom": 6,
    "Ice Cream": 3.64, "Instant Ramen": 3.63, "Holiday Drink": 3.8, "Chill Flame": 3.58, "Vice Cream": 3.58, "Snake Box": 3.63,
    "Xmas Stocking": 3.62, "Candy Cane": 3.65, "Tama Gadget": 3.69, "Mood Pack": 4.0, "Hex Pot": 4.44, "Liberty Figure": 4.6,
    "Swag Bag": 5.0, "Desk Calendar": 5.46, "Light Sword": 5.99, "Lol Pop": 3.7, "Party Sparkler": 3.7, "Homemade Cake": 3.8,
    "Jester Hat": 3.7, "B-Day Candle": 3.7, "Jingle Bells": 3.8, "Cookie Heart": 3.7, "Whip Cupcake": 3.6, "Lunar Snake": 3.6,
    "Pet Snake": 3.7, "Big Year": 3.8, "Snow Globe": 4.2, "Snow Mittens": 4.2, "Winter Wreath": 4.0, "Ginger Cookie": 4.0,
    "Santa Hat": 4.3, "Spiced Wine": 4.3, "Hypno Lollipop": 4.0, "Star Notepad": 4.0, "Easter Egg": 4.0, "Clover Pin": 4.0,
    "Fresh Socks": 3.9, "Input Key": 3.9, "Happy Brownie": 3.8, "Spring Basket": 4.0, "Pretty Posy": 4.0, "Money Pot": 4.0,
}

def model_mult(permille):  # редкие модели дороже флора коллекции: 2% -> x1, 1% -> x1.4, 0.5% -> x2, 0.1% -> x4
    return min(4.0, max(1.0, (20 / max(permille, 1)) ** 0.5))

MODELS = {g: dict((m, p) for m, p in c["models"]) for g, c in CATALOG.items()}

def model_img(gift, model, size=256):  # лёгкое превью webp с нашего сервера, см. /img
    return f"/img/{size}?" + urllib.parse.urlencode({"g": gift, "m": model})

def nft_value(gift, model):
    perm = MODELS.get(gift, {}).get(model)
    if perm is None: raise HTTPException(404, "Нет такой модели")
    return round(FLOORS.get(gift, DEFAULT_FLOOR) * TON_STARS * model_mult(perm))

def floor_stars(gift): return round(FLOORS.get(gift, DEFAULT_FLOOR) * TON_STARS)

# ---------- база ----------
db = sqlite3.connect("giftmafia_v2.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, name TEXT, created INT, last_free INT DEFAULT 0, balance INT DEFAULT 0, ref_by INT DEFAULT 0, ref_earned INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, title TEXT, price INT DEFAULT 0, emoji TEXT, cat TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS prizes(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INT, kind TEXT DEFAULT 'nft', name TEXT, emoji TEXT DEFAULT '🎁',
  gift TEXT DEFAULT '', model TEXT DEFAULT '', img TEXT DEFAULT '', stars INT DEFAULT 0, weight REAL);
CREATE TABLE IF NOT EXISTS wins(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, case_id INT, kind TEXT DEFAULT 'nft', prize TEXT, emoji TEXT DEFAULT '🎁',
  gift TEXT DEFAULT '', model TEXT DEFAULT '', img TEXT DEFAULT '', value INT DEFAULT 0, source TEXT DEFAULT 'case',
  status TEXT, story_at INT DEFAULT 0, shares INT DEFAULT 0, last_share INT DEFAULT 0, created INT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS plinko(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, bet INT, rows INT, risk TEXT, slot INT, mult REAL, payout INT, created INT);
CREATE TABLE IF NOT EXISTS mines(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, bet INT, bombs INT, field TEXT, seed TEXT, opened TEXT DEFAULT '[]',
  status TEXT DEFAULT 'live', payout INT DEFAULT 0, created INT);
""")


def q(sql, *a): return [dict(r) for r in db.execute(sql, a).fetchall()]
def q1(sql, *a):
    r = db.execute(sql, a).fetchone()
    return dict(r) if r else None
def run(sql, *a):
    c = db.execute(sql, a); db.commit(); return c.lastrowid
def changed(sql, *a):  # сколько строк обновлено (атомарные списания)
    c = db.execute(sql, a); db.commit(); return c.rowcount


# ---------- кейсы ----------
def solve_weights(values, target):
    """Веса w ~ v^-a, подбираем a так, чтобы матожидание = target."""
    def ev(a):
        w = [v ** -a for v in values]; return sum(x * v for x, v in zip(w, values)) / sum(w)
    lo, hi = -2.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ev(mid) > target else (lo, mid)
    w = [v ** -lo for v in values]; s = sum(w)
    return [round(x / s * 100, 6) for x in w]


def nft_item(gift, model):
    return {"kind": "nft", "gift": gift, "model": model, "name": f"{gift} · {model}", "img": model_img(gift, model), "stars": nft_value(gift, model)}


def stars_item(n): return {"kind": "stars", "gift": "", "model": "", "name": "На баланс", "img": "", "stars": n}


def pick_models(gifts, count, rng, rare_first=False):
    out = []
    for g in gifts:
        ms = CATALOG[g]["models"]
        out += [nft_item(g, m) for m, _ in (ms[:count] if rare_first else rng.sample(ms, min(count, len(ms))))]
    return out


NICE = [49, 79, 99, 149, 199, 249, 299, 399, 499, 749, 999, 1499, 1999, 2499, 2999, 3999, 4999, 7499, 9999, 14999, 19999,
        24999, 29999, 39999, 49999, 74999, 99999, 149999, 199999, 299999]
def nice(x): return min(NICE, key=lambda n: abs(n - x))


def near(value, rng, pool=None, spread=0.15):
    """Случайная модель NFT стоимостью около value (из всего каталога или из коллекций pool)."""
    cands = [(g, m) for g in (pool or CATALOG) for m in MODELS[g]]
    vals = {(g, m): nft_value(g, m) for g, m in cands}
    best = min(cands, key=lambda k: abs(vals[k] - value))
    close = [k for k in cands if abs(vals[k] - vals[best]) <= vals[best] * spread]
    return nft_item(*rng.choice(close))


THEMES = [  # тематические кейсы: (название, коллекции)
    ("Зимний", ["Santa Hat", "Snow Globe", "Xmas Stocking", "Candy Cane", "Ginger Cookie", "Winter Wreath", "Snow Mittens", "Sleigh Bell", "Jingle Bells", "Holiday Drink", "Spiced Wine", "Big Year"]),
    ("Хэллоуин", ["Mad Pumpkin", "Witch Hat", "Hex Pot", "Voodoo Doll", "Skull Flower", "Evil Eye", "Spy Agaric", "Scared Cat", "Trapped Heart", "Flying Broom", "Crystal Ball", "Electric Skull"]),
    ("Любовь", ["Love Potion", "Love Candle", "Cookie Heart", "Eternal Rose", "Valentine Box", "Cupid Charm", "Bonded Ring", "Diamond Ring", "Lush Bouquet", "Heart Locket"]),
    ("Сладкий", ["Ice Cream", "Vice Cream", "Lol Pop", "Hypno Lollipop", "Homemade Cake", "Whip Cupcake", "Mousse Cake", "Bunny Muffin", "Berry Box", "Happy Brownie", "Jelly Bunny", "Instant Ramen"]),
    ("Westside", ["Snoop Dogg", "Snoop Cigar", "Low Rider", "Westside Sign", "Swag Bag"]),
    ("Чемпион", ["UFC Strike", "Khabib's Papakha", "Victory Medal", "Mighty Arm", "Heroic Helmet", "Surge Board"]),
    ("Роскошь", ["Signet Ring", "Gem Signet", "Swiss Watch", "Perfume Bottle", "Vintage Cigar", "Nail Bracelet", "Precious Peach", "Astral Shard", "Ion Gem", "Loot Bag"]),
    ("Магия", ["Magic Potion", "Genie Lamp", "Crystal Ball", "Witch Hat", "Hex Pot", "Astral Shard", "Eternal Candle", "Star Notepad", "Mirage Lamp"]),
]


def build_cases():
    """Кейсы собираются из каталога: цена «красивая», у каждого кейса есть дешёвые призы, призы около цены и джекпоты.
    Веса подбираются так, чтобы средний возврат был CASE_RTP. Потом цены и веса можно править в админке."""
    if (q1("SELECT v FROM meta WHERE k='economy'") or {}).get("v") == ECONOMY_VERSION: return
    run("DELETE FROM prizes"); run("DELETE FROM cases")
    rng = random.Random(11)
    C = []  # (id, title, price, cat, items, rtp)
    free = [stars_item(n) for n in (1, 2, 3, 5, 10, 25)] + [near(v, rng) for v in (260, 280, 300, 330)]
    C.append((1, "Подарок дня", 0, "free", free, None))
    for i, (t, p) in enumerate([("Мелочь", 49), ("Сдача", 99), ("Копилка", 149), ("Заначка", 249), ("Кошелёк", 399), ("Сейф", 749)]):
        items = [stars_item(round(p * k)) for k in (0.2, 0.4, 0.6, 0.8)]
        items += [near(p * k, rng) for k in (1.3, 2, 3, 5, 8, 15, 30)]
        C.append((10 + i, t, p, "change", items, CASE_RTP))
    for i, (t, p) in enumerate([("Орёл или решка", 199), ("Всё или ничего", 499), ("Двойной шанс", 999), ("Ва-банк", 2499)]):
        C.append((20 + i, t, p, "fifty", [near(p * 1.3, rng, spread=0.05)], None))  # проигрышный приз добавим ниже
    for i, (t, p) in enumerate([("Семья", 499), ("Капо", 999), ("Консильери", 1499), ("Крёстный отец", 2499), ("Дон", 4999),
                                ("Босс", 9999), ("Легенда", 24999)]):
        items = [stars_item(round(p * k)) for k in (0.3, 0.5, 0.7)]
        items += [near(p * k, rng) for k in (1, 1.5, 2, 3, 5, 10, 25, 50)]
        C.append((30 + i, t, p, "premium", items, CASE_RTP))
    for i, (t, pool) in enumerate(THEMES):
        pool = [g for g in pool if g in CATALOG]
        cheapest = min(nft_value(g, m) for g in pool for m in MODELS[g])
        p = nice(cheapest * 1.25)
        items = [stars_item(round(p * k)) for k in (0.15, 0.3, 0.5)]
        items += [near(p * k, rng, pool) for k in (0.8, 1.1, 1.5, 2, 3, 5, 8, 15, 30)]
        C.append((60 + i, t, p, "theme", list({it["name"]: it for it in items}.values()), CASE_RTP))
    for i, g in enumerate(["Plush Pepe", "Durov's Cap", "Precious Peach", "Heart Locket", "Snoop Dogg", "Scared Cat", "Toy Bear", "Diamond Ring",
                           "Signet Ring", "Swiss Watch", "Astral Shard", "Ion Gem", "Mini Oscar", "Perfume Bottle", "Magic Potion", "Genie Lamp",
                           "Kissed Frog", "Vintage Cigar", "Loot Bag", "Nail Bracelet"]):
        if g not in CATALOG: continue
        f = floor_stars(g); p = nice(f * 0.45)
        ms = sorted(CATALOG[g]["models"], key=lambda x: x[1])  # от редких к частым
        items = [stars_item(round(p * k)) for k in (0.25, 0.5, 0.75)]
        items += [nft_item(g, m) for m, _ in ms[:4]] + [nft_item(g, m) for m, _ in rng.sample(ms[4:], min(6, len(ms) - 4))]
        C.append((100 + i, g, p, "coll", items, CASE_RTP))
    for cid, title, price, cat, items, rtp in C:
        run("INSERT INTO cases(id,title,price,emoji,cat) VALUES(?,?,?,?,?)", cid, title, price, "🎁", cat)
        if cat == "fifty":  # честные 50/50: проигрыш - звёзды, выигрыш - NFT около x1.3
            win = items[0]; lose = max(1, round(2 * CASE_RTP * price - win["stars"]))
            items, ws = [stars_item(lose), win], [50, 50]
        else:
            ws = solve_weights([it["stars"] for it in items], price * rtp if rtp else 4)
        for it, w in zip(items, ws):
            run("INSERT INTO prizes(case_id,kind,name,gift,model,img,stars,weight) VALUES(?,?,?,?,?,?,?,?)",
                cid, it["kind"], it["name"], it["gift"], it["model"], it["img"], it["stars"], w)
    run("INSERT OR REPLACE INTO meta(k,v) VALUES('economy',?)", ECONOMY_VERSION)


build_cases()
# стоимость NFT пересчитывается из FLOORS при каждом старте
for p in q("SELECT id,gift,model FROM prizes WHERE kind='nft'"):
    try: run("UPDATE prizes SET stars=?,img=? WHERE id=?", nft_value(p["gift"], p["model"]), model_img(p["gift"], p["model"]), p["id"])
    except HTTPException: pass
for w in q("SELECT id,gift,model FROM wins WHERE kind='nft' AND img NOT LIKE '/img/%'"):  # старые ссылки на CDN -> превью
    run("UPDATE wins SET img=? WHERE id=?", model_img(w["gift"], w["model"]), w["id"])


def roll(case_id):
    p = q("SELECT * FROM prizes WHERE case_id=? AND weight>0", case_id)
    if not p: raise HTTPException(500, "В кейсе нет призов")
    return random.choices(p, weights=[x["weight"] for x in p])[0]


def add_win(uid, it, status, source="case", case_id=0):
    wid = run("INSERT INTO wins(user_id,case_id,kind,prize,gift,model,img,value,source,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              uid, case_id, it["kind"], it["name"], it["gift"], it["model"], it["img"], it["stars"], source, status, int(time.time()))
    return q1("SELECT * FROM wins WHERE id=?", wid)


def open_one(uid, case_id, nft_status):
    p = roll(case_id)
    if p["kind"] == "stars":
        credit(uid, p["stars"])
        return add_win(uid, p, "credited", case_id=case_id)
    return add_win(uid, p, nft_status, case_id=case_id)


# ---------- картинки моделей ----------
# Оригиналы PNG качаются один раз с cdn.changes.tg (запасной вариант - api.changes.tg) и хранятся в static/cache,
# в мини-апп отдаются уменьшенные webp (в 5-10 раз легче), чтобы экраны грузились быстро.
THUMB_SIZES = (128, 256, 512)
for d in ("static/cache", *(f"static/cache/t{s}" for s in THUMB_SIZES)): os.makedirs(d, exist_ok=True)


def _key(gift, model): return hashlib.sha1(f"{gift}\n{model}".encode()).hexdigest()[:24]


def _save(path, data):
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    with open(tmp, "wb") as f: f.write(data)
    os.replace(tmp, path)


def model_png(gift, model):
    """Путь к оригинальной картинке модели (скачивает при первом обращении) или '' если недоступна."""
    path = f"static/cache/{_key(gift, model)}.png"
    if os.path.exists(path): return path
    g, m = urllib.parse.quote(gift, safe=""), urllib.parse.quote(model, safe="")
    for url in (f"https://cdn.changes.tg/gifts/models/{g}/png/{m}.png", f"https://api.changes.tg/model/{g}/{m}.png?size=512"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "giftmafia/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r: _save(path, r.read())
            return path
        except Exception: continue
    return ""


def warm_thumbs():  # заранее готовим превью призов кейсов, чтобы первый вход был быстрым
    for p in q("SELECT DISTINCT gift,model FROM prizes WHERE kind='nft'"):
        for size in (128, 256):
            try: model_thumb(p["gift"], p["model"], size)
            except Exception: pass


def model_thumb(gift, model, size):
    path = f"static/cache/t{size}/{_key(gift, model)}.webp"
    if os.path.exists(path): return path
    src = model_png(gift, model)
    if not src: return ""
    im = Image.open(src).convert("RGBA"); im.thumbnail((size, size), Image.LANCZOS)
    out = io.BytesIO(); im.save(out, "WEBP", quality=85, method=4); _save(path, out.getvalue())
    return path


def font(sz, bold=True):
    return ImageFont.truetype(f"static/fonts/DejaVuSans{'-Bold' if bold else ''}.ttf", sz)


def glow(W, H, cx, cy, r, a=38, color=(255, 255, 255)):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((cx - r, cy - r, cx + r, cy + r), fill=a)
    return m.filter(ImageFilter.GaussianBlur(r // 2))


def put_nft(base, path, box, cx, cy):
    im = Image.open(path).convert("RGBA"); k = box / max(im.size); im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0)); a = im.split()[3].point(lambda v: v * 0.55)
    sh.paste((0, 0, 0, 255), (cx - im.width // 2, cy - im.height // 2 + 24), a); sh = sh.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(sh); base.alpha_composite(im, (cx - im.width // 2, cy - im.height // 2))


def story_image(w):  # сторис 1080x1920 из выигранного NFT
    W, H = 1080, 1920
    base = Image.new("RGBA", (W, H), "#151626")
    base.paste((112, 96, 255, 255), (0, 0), glow(W, H, W // 2, 840, 560, 70))
    d = ImageDraw.Draw(base)
    d.text((W // 2, 150), "GiftMafia", font=font(54), fill="#f5f5f7", anchor="mm")
    img = model_png(w["gift"], w["model"]) if w["gift"] else ""
    if img: put_nft(base, img, 640, W // 2, 840)
    d.text((W // 2, 1290), w["gift"] or w["prize"], font=font(84), fill="#f5f5f7", anchor="mm")
    d.text((W // 2, 1390), w["model"] or "выигрыш в GiftMafia", font=font(44, False), fill="#a7a9c9", anchor="mm")
    d.rounded_rectangle((W // 2 - 270, 1560, W // 2 + 270, 1660), 50, fill="#6c63ff")
    d.text((W // 2, 1610), f"@{BOT_USERNAME or 'GiftMafia'}", font=font(40), fill="#ffffff", anchor="mm")
    out = io.BytesIO(); base.convert("RGB").save(out, "JPEG", quality=90); return out.getvalue()


def make_banner():  # баннер для /start в стиле мини-аппа
    W, H = 1280, 640
    base = Image.new("RGBA", (W, H), "#151626")
    base.paste((112, 96, 255, 255), (0, 0), glow(W, H, 930, 320, 330, 60))
    d = ImageDraw.Draw(base)
    d.text((90, 210), "GiftMafia", font=font(96), fill="#f5f5f7", anchor="lm")
    d.text((92, 310), "NFT-кейсы, мины и апгрейды", font=font(38, False), fill="#a7a9c9", anchor="lm")
    d.text((92, 360), "Подарок дня — бесплатно", font=font(38, False), fill="#a7a9c9", anchor="lm")
    d.rounded_rectangle((90, 430, 400, 510), 40, fill="#6c63ff")
    d.text((245, 470), "Играть", font=font(32), fill="#ffffff", anchor="mm")
    d.rounded_rectangle((740, 80, 1120, 560), 44, fill="#23243b", outline="#34365a", width=3)
    img = model_png("Plush Pepe", CATALOG["Plush Pepe"]["models"][0][0]) if "Plush Pepe" in CATALOG else ""
    if img: put_nft(base, img, 300, 930, 320)
    base.convert("RGB").save("static/banner.jpg", quality=92)


# ---------- auth ----------
def auth(x_init: str = Header("")):
    d = dict(parse_qsl(x_init))
    h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not h or not hmac.compare_digest(hmac.new(key, s.encode(), hashlib.sha256).hexdigest(), h) \
            or time.time() - int(d.get("auth_date", 0)) > 86400:
        raise HTTPException(401, "bad init data")
    u = json.loads(d["user"])
    if not q1("SELECT 1 FROM users WHERE id=?", u["id"]):
        sp = d.get("start_param", "")
        ref = int(sp[1:]) if sp[:1] == "r" and sp[1:].isdigit() and int(sp[1:]) != u["id"] and q1("SELECT 1 FROM users WHERE id=?", int(sp[1:])) else 0
        run("INSERT INTO users(id,username,name,created,ref_by) VALUES(?,?,?,?,?)", u["id"], u.get("username"), u.get("first_name"), int(time.time()), ref)
        if ref: credit(ref, REF_BONUS, True)
    return u["id"]


def credit(uid, amount, ref=False):
    run("UPDATE users SET balance=balance+?, ref_earned=ref_earned+? WHERE id=?", amount, amount if ref else 0, uid)


def charge(uid, amount):
    if changed("UPDATE users SET balance=balance-? WHERE id=? AND balance>=?", amount, uid, amount) == 0: raise HTTPException(400, "Недостаточно ⭐ на балансе")


def take_item(uid, wid):
    """Забрать подарок из инвентаря (ставка в минах / источник апгрейда)."""
    if changed("UPDATE wins SET status='used' WHERE id=? AND user_id=? AND status='ready'", wid, uid) == 0: raise HTTPException(400, "Подарок недоступен")
    return q1("SELECT * FROM wins WHERE id=?", wid)


def story_sig(wid): return hmac.new(TOKEN.encode(), f"story{wid}".encode(), hashlib.sha256).hexdigest()[:16]
def story_url(wid): return f"{WEBAPP_URL}/story/{wid}/{story_sig(wid)}.jpg"


def admin(x_admin: str = Header("")):
    if not hmac.compare_digest(x_admin, ADMIN_TOKEN): raise HTTPException(401, "admin only")


def own_win(wid, uid):
    w = q1("SELECT * FROM wins WHERE id=? AND user_id=?", wid, uid)
    if not w: raise HTTPException(404, "нет такого выигрыша")
    return w


# ---------- bot ----------
@dp.message(CommandStart())
async def start(m):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть GiftMafia", web_app=WebAppInfo(url=WEBAPP_URL), style="primary")],
        [InlineKeyboardButton(text="🎉 Подарок дня бесплатно", web_app=WebAppInfo(url=WEBAPP_URL), style="success")]])
    await m.answer_photo(FSInputFile("static/banner.jpg"), caption=(
        "🎩 <b>GiftMafia</b>\n\n"
        "📦 NFT-кейсы с подарками Telegram\n"
        "💣 Мины и 🚀 апгрейды\n"
        "🎁 Подарок дня — бесплатно каждые 24 часа\n"
        "👥 Приглашай друзей и получай ⭐\n\n"
        ""), parse_mode="HTML", reply_markup=kb)


@dp.pre_checkout_query()
async def pre(p): await p.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(m):
    amount = int(m.successful_payment.invoice_payload.split(":")[1])
    credit(m.from_user.id, amount)
    await m.answer(f"Баланс пополнен на ⭐ {amount}.")


# ---------- app ----------
@asynccontextmanager
async def lifespan(_):
    global BOT_USERNAME
    BOT_USERNAME = (await bot.get_me()).username
    await asyncio.to_thread(make_banner)
    warm = asyncio.create_task(asyncio.to_thread(warm_thumbs))
    t = asyncio.create_task(dp.start_polling(bot))
    yield
    t.cancel()

app = FastAPI(lifespan=lifespan)


def inventory(uid):
    ws = q("SELECT * FROM wins WHERE user_id=? AND kind='nft' AND status IN('locked','ready','requested','sent') ORDER BY id DESC LIMIT 200", uid)
    for w in ws: w["story_url"] = story_url(w["id"])
    return ws


@app.get("/api/state")
def state(uid: int = Depends(auth)):
    u = q1("SELECT * FROM users WHERE id=?", uid)
    cases = q("SELECT * FROM cases ORDER BY price")
    for c in cases: c["prizes"] = q("SELECT id,kind,name,gift,model,img,stars,weight FROM prizes WHERE case_id=? AND weight>0 ORDER BY stars DESC", c["id"])
    g = q1("SELECT * FROM mines WHERE user_id=? AND status='live' ORDER BY id DESC LIMIT 1", uid)
    return {"cases": cases, "free_in": max(0, u["last_free"] + FREE_COOLDOWN - int(time.time())),
            "inventory": inventory(uid), "balance": u["balance"], "mines": mines_view(g) if g else None,
            "refs": q1("SELECT COUNT(*) n FROM users WHERE ref_by=?", uid)["n"], "ref_earned": u["ref_earned"],
            "ref_bonus": REF_BONUS, "ref_percent": REF_PERCENT, "uid": uid, "need": FRIENDS_REQUIRED, "bot": BOT_USERNAME,
            "sell_rate": SELL_RATE, "mines_edge": MINES_EDGE, "mines_max": MINES_MAX_WIN, "upgrade_edge": UPGRADE_EDGE, "topup_min": TOPUP_MIN, "topup_max": TOPUP_MAX,
            "plinko": PLINKO, "plinko_max": PLINKO_MAX_BET, "upgrade_max": UPGRADE_MAX_CHANCE}


@app.get("/api/catalog")
def catalog():
    """Все коллекции с флором; модели и редкость — в /static/gifts.json."""
    return {"ton_stars": TON_STARS, "floors_ton": {g: FLOORS.get(g, DEFAULT_FLOOR) for g in CATALOG}}


@app.post("/api/free")
def free(uid: int = Depends(auth)):
    if changed("UPDATE users SET last_free=? WHERE id=? AND last_free<=?", int(time.time()), uid, int(time.time()) - FREE_COOLDOWN) == 0: raise HTTPException(400, "Кейс ещё не готов")
    return open_one(uid, 1, "locked")


@app.post("/api/topup/{amount}")
async def topup(amount: int, uid: int = Depends(auth)):
    if not TOPUP_MIN <= amount <= TOPUP_MAX: raise HTTPException(400, f"Сумма от {TOPUP_MIN} до {TOPUP_MAX} ⭐")
    link = await bot.create_invoice_link(title="Пополнение баланса", description=f"{amount} ⭐ на баланс GiftMafia", payload=f"top:{amount}",
                                         currency="XTR", prices=[LabeledPrice(label="Пополнение", amount=amount)])
    return {"link": link}


@app.post("/api/buy/{case_id}")
def buy(case_id: int, n: int = 1, uid: int = Depends(auth)):
    if not 1 <= n <= MAX_MULTI: raise HTTPException(400, f"От 1 до {MAX_MULTI} кейсов за раз")
    c = q1("SELECT * FROM cases WHERE id=? AND price>0", case_id)
    if not c: raise HTTPException(404, "Нет кейса")
    if not q1("SELECT 1 FROM prizes WHERE case_id=? AND weight>0 LIMIT 1", case_id): raise HTTPException(500, "В кейсе нет призов")
    cost = c["price"] * n
    charge(uid, cost)
    ref = q1("SELECT ref_by FROM users WHERE id=?", uid)["ref_by"]
    if ref and cost * REF_PERCENT // 100: credit(ref, cost * REF_PERCENT // 100, True)
    return {"wins": [open_one(uid, case_id, "ready") for _ in range(n)]}  # платные кейсы выводятся без заданий


@app.get("/api/live")
def live(uid: int = Depends(auth)):
    return q("SELECT w.kind,w.prize,w.gift,w.model,w.img,w.value,substr(u.name,1,12) AS who FROM wins w JOIN users u ON u.id=w.user_id "
             "WHERE w.source!='mines' ORDER BY w.id DESC LIMIT 20")


# ---------- инвентарь ----------
@app.post("/api/win/{wid}/sell")
def sell(wid: int, uid: int = Depends(auth)):
    w = take_item(uid, wid)
    run("UPDATE wins SET status='sold' WHERE id=?", wid)
    amount = int(w["value"] * SELL_RATE); credit(uid, amount)
    return {"amount": amount}


@app.get("/story/{wid}/{sig}.jpg")
def story_img(wid: int, sig: str):
    w = q1("SELECT * FROM wins WHERE id=?", wid)
    if not w or not hmac.compare_digest(sig, story_sig(wid)): raise HTTPException(404)
    return Response(story_image(w), media_type="image/jpeg")


@app.post("/api/win/{wid}/story")
def story(wid: int, uid: int = Depends(auth)):
    w = own_win(wid, uid)
    if w["status"] == "locked" and not w["story_at"]: run("UPDATE wins SET story_at=? WHERE id=?", int(time.time()), wid)
    return {"ok": True}


@app.post("/api/win/{wid}/prepare")
async def prepare(wid: int, uid: int = Depends(auth)):
    w = own_win(wid, uid)
    text = (f"🎁 Я выиграл {w['prize']} в GiftMafia! Подарок дня бесплатно, "
            f"забирай: https://t.me/{BOT_USERNAME}")
    res = InlineQueryResultArticle(id=f"w{wid}", title="GiftMafia", input_message_content=InputTextMessageContent(message_text=text))
    pm = await bot.save_prepared_inline_message(user_id=uid, result=res, allow_user_chats=True)
    return {"id": pm.id}


@app.post("/api/win/{wid}/shared")
def shared(wid: int, uid: int = Depends(auth)):
    w = own_win(wid, uid)
    if w["status"] != "locked" or w["shares"] >= FRIENDS_REQUIRED or time.time() - w["last_share"] < 3: return {"shares": w["shares"]}
    run("UPDATE wins SET shares=shares+1,last_share=? WHERE id=?", int(time.time()), wid)
    return {"shares": w["shares"] + 1}


@app.post("/api/win/{wid}/withdraw")
async def withdraw(wid: int, uid: int = Depends(auth)):
    w = own_win(wid, uid)
    if w["status"] == "locked":
        if not w["story_at"] or time.time() - w["story_at"] < STORY_MIN_DELAY or w["shares"] < FRIENDS_REQUIRED:
            raise HTTPException(400, "Сначала выполните все задания")
        run("UPDATE wins SET status='ready' WHERE id=?", wid); w["status"] = "ready"
    if changed("UPDATE wins SET status='requested' WHERE id=? AND status='ready'", wid) == 0: raise HTTPException(400, "Уже подана заявка")
    if ADMIN_CHAT_ID:
        u = q1("SELECT * FROM users WHERE id=?", uid)
        await bot.send_message(ADMIN_CHAT_ID, f"Заявка #{wid}: {w['prize']} → @{u['username'] or u['id']} (id {uid})")
    return {"ok": True}


@app.post("/api/win/{wid}/unlock")
def unlock(wid: int, uid: int = Depends(auth)):
    """Подарок из бесплатного кейса после заданий можно оставить в инвентаре (продать, апгрейд, мины)."""
    w = own_win(wid, uid)
    if w["status"] != "locked": raise HTTPException(400, "Подарок уже доступен")
    if not w["story_at"] or time.time() - w["story_at"] < STORY_MIN_DELAY or w["shares"] < FRIENDS_REQUIRED:
        raise HTTPException(400, "Сначала выполните все задания")
    run("UPDATE wins SET status='ready' WHERE id=?", wid); return {"ok": True}


# ---------- мины ----------
def mines_mult(bombs, k):
    m = 1.0
    for i in range(k): m *= (CELLS - i) / (CELLS - bombs - i)
    return round(m * MINES_EDGE, 2) if k else 1.0


def mines_view(g):
    opened = json.loads(g["opened"])
    v = {"id": g["id"], "bet": g["bet"], "bombs": g["bombs"], "opened": opened, "status": g["status"], "payout": g["payout"],
         "mult": mines_mult(g["bombs"], len(opened)), "hash": hashlib.sha256(f"{g['seed']}:{g['field']}".encode()).hexdigest()}
    if g["status"] != "live": v.update(field=json.loads(g["field"]), seed=g["seed"])
    return v


def live_game(gid, uid):
    g = q1("SELECT * FROM mines WHERE id=? AND user_id=? AND status='live'", gid, uid)
    if not g: raise HTTPException(404, "Игра уже закончилась")
    return g


@app.post("/api/mines/start")
def mines_start(b: dict = Body(...), uid: int = Depends(auth)):
    bombs = int(b.get("bombs", 3))
    if not 1 <= bombs <= 24: raise HTTPException(400, "Мин от 1 до 24")
    if q1("SELECT 1 FROM mines WHERE user_id=? AND status='live'", uid): raise HTTPException(400, "Сначала закончите текущую игру")
    if b.get("win_id"): bet = take_item(uid, int(b["win_id"]))["value"]
    else:
        bet = int(b.get("bet", 0))
        if bet < 1: raise HTTPException(400, "Ставка от 1 ⭐")
        charge(uid, bet)
    field = sorted(secrets.SystemRandom().sample(range(CELLS), bombs))
    gid = run("INSERT INTO mines(user_id,bet,bombs,field,seed,created) VALUES(?,?,?,?,?,?)", uid, bet, bombs, json.dumps(field), secrets.token_hex(16), int(time.time()))
    return mines_view(q1("SELECT * FROM mines WHERE id=?", gid))


@app.post("/api/mines/{gid}/open/{cell}")
def mines_open(gid: int, cell: int, uid: int = Depends(auth)):
    g = live_game(gid, uid)
    opened = json.loads(g["opened"])
    if not 0 <= cell < CELLS or cell in opened: raise HTTPException(400, "Клетка уже открыта")
    opened.append(cell)
    if cell in json.loads(g["field"]):
        run("UPDATE mines SET opened=?,status='lost' WHERE id=?", json.dumps(opened), gid)
    else:
        run("UPDATE mines SET opened=? WHERE id=?", json.dumps(opened), gid)
        if len(opened) == CELLS - g["bombs"] or g["bet"] * mines_mult(g["bombs"], len(opened)) >= MINES_MAX_WIN: return mines_cashout(gid, uid)
    return mines_view(q1("SELECT * FROM mines WHERE id=?", gid))


@app.post("/api/mines/{gid}/cashout")
def mines_cashout(gid: int, uid: int = Depends(auth)):
    g = live_game(gid, uid)
    k = len(json.loads(g["opened"]))
    if not k: raise HTTPException(400, "Откройте хотя бы одну клетку")
    payout = min(MINES_MAX_WIN, int(g["bet"] * mines_mult(g["bombs"], k)))
    if changed("UPDATE mines SET status='won',payout=? WHERE id=? AND status='live'", payout, gid): credit(uid, payout)
    return mines_view(q1("SELECT * FROM mines WHERE id=?", gid))


# ---------- плинко ----------
# Базовые таблицы множителей (ряды -> риск -> ячейки слева направо), затем масштабируются до PLINKO_RTP.
PLINKO_BASE = {
    8: {"low": [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6], "mid": [13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
        "high": [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29]},
    12: {"low": [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10], "mid": [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
         "high": [170, 24, 8.1, 2, 0.7, 0.2, 0.2, 0.2, 0.7, 2, 8.1, 24, 170]},
    16: {"low": [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1, 0.5, 1, 1.1, 1.2, 1.4, 1.4, 2, 9, 16],
         "mid": [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110],
         "high": [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000]},
}


def _plinko_table(rows, base):
    probs = [math.comb(rows, k) / 2 ** rows for k in range(rows + 1)]
    rtp = lambda t: sum(p * m for p, m in zip(probs, t))
    rnd = lambda k: [round(m * k) if m * k >= 100 else max(0.1, round(m * k, 1)) for m in base]
    k = PLINKO_RTP / rtp(base)
    while rtp(rnd(k)) > PLINKO_RTP + 0.004: k *= 0.997  # после округления возврат не выше цели
    return rnd(k)


PLINKO = {r: {risk: _plinko_table(r, t) for risk, t in v.items()} for r, v in PLINKO_BASE.items()}


@app.post("/api/plinko")
def plinko(b: dict = Body(...), uid: int = Depends(auth)):
    rows, risk = int(b.get("rows", 12)), b.get("risk", "mid")
    if rows not in PLINKO or risk not in PLINKO[rows]: raise HTTPException(400, "Неверные настройки")
    bet = int(b.get("bet", 0))
    if not 1 <= bet <= PLINKO_MAX_BET: raise HTTPException(400, f"Ставка от 1 до {PLINKO_MAX_BET} ⭐")
    charge(uid, bet)
    rnd = secrets.SystemRandom()
    path = [rnd.randrange(2) for _ in range(rows)]
    slot = sum(path); mult = PLINKO[rows][risk][slot]; payout = int(bet * mult)
    if payout: credit(uid, payout)
    run("INSERT INTO plinko(user_id,bet,rows,risk,slot,mult,payout,created) VALUES(?,?,?,?,?,?,?,?)", uid, bet, rows, risk, slot, mult, payout, int(time.time()))
    return {"path": path, "slot": slot, "mult": mult, "payout": payout, "balance": q1("SELECT balance FROM users WHERE id=?", uid)["balance"]}


# ---------- апгрейд ----------
@app.post("/api/upgrade")
def upgrade(b: dict = Body(...), uid: int = Depends(auth)):
    gift, model = b.get("gift", ""), b.get("model", "")
    if gift not in CATALOG: raise HTTPException(404, "Нет такой коллекции")
    target = nft_value(gift, model)
    src = int(b["stars"]) if not b.get("win_id") else own_win(int(b["win_id"]), uid)["value"]
    if src < 1: raise HTTPException(400, "Выберите, что улучшать")
    if src >= target: raise HTTPException(400, "Цель должна быть дороже ставки")
    chance = min(UPGRADE_MAX_CHANCE, src / target * UPGRADE_EDGE)
    if b.get("win_id"): take_item(uid, int(b["win_id"]))
    else: charge(uid, src)
    r = secrets.SystemRandom().random()
    win = add_win(uid, nft_item(gift, model), "ready", "upgrade") if r < chance else None
    return {"ok": win is not None, "chance": chance, "roll": r, "win": win}


# ---------- admin ----------
@app.get("/api/admin/requests", dependencies=[Depends(admin)])
def a_req():
    return q("SELECT w.*,u.username,u.name FROM wins w JOIN users u ON u.id=w.user_id WHERE status IN('requested','sent','rejected') ORDER BY (status='requested') DESC, w.id DESC LIMIT 100")


@app.post("/api/admin/win/{wid}/{act}", dependencies=[Depends(admin)])
async def a_win(wid: int, act: str):
    if act not in ("sent", "rejected"): raise HTTPException(400)
    w = q1("SELECT * FROM wins WHERE id=?", wid)
    run("UPDATE wins SET status=? WHERE id=?", act, wid)
    if act == "sent":
        try: await bot.send_message(w["user_id"], f"✅ Ваш подарок {w['prize']} отправлен!")
        except Exception: pass
    return {"ok": True}


@app.get("/api/admin/prizes", dependencies=[Depends(admin)])
def a_prizes(): return {"cases": q("SELECT * FROM cases ORDER BY price"), "prizes": q("SELECT * FROM prizes ORDER BY case_id,stars DESC")}


@app.post("/api/admin/prize", dependencies=[Depends(admin)])
def a_prize_add(b: dict):
    it = nft_item(b["gift"], b["model"]) if b.get("kind", "nft") == "nft" else stars_item(int(b["stars"]))
    run("INSERT INTO prizes(case_id,kind,name,gift,model,img,stars,weight) VALUES(?,?,?,?,?,?,?,?)",
        int(b["case_id"]), it["kind"], it["name"], it["gift"], it["model"], it["img"], it["stars"], float(b["weight"]))
    return {"ok": True}


@app.patch("/api/admin/prize/{pid}", dependencies=[Depends(admin)])
def a_prize_edit(pid: int, b: dict):
    run("UPDATE prizes SET weight=? WHERE id=?", float(b["weight"]), pid); return {"ok": True}


@app.delete("/api/admin/prize/{pid}", dependencies=[Depends(admin)])
def a_prize_del(pid: int):
    run("DELETE FROM prizes WHERE id=?", pid); return {"ok": True}


@app.patch("/api/admin/case/{cid}", dependencies=[Depends(admin)])
def a_case(cid: int, b: dict):
    run("UPDATE cases SET price=? WHERE id=? AND id!=1", int(b["price"]), cid); return {"ok": True}


@app.get("/api/admin/stats", dependencies=[Depends(admin)])
def a_stats():
    return {"users": q1("SELECT COUNT(*) n FROM users")["n"], "wins": q1("SELECT COUNT(*) n FROM wins")["n"],
            "requested": q1("SELECT COUNT(*) n FROM wins WHERE status='requested'")["n"],
            "sent": q1("SELECT COUNT(*) n FROM wins WHERE status='sent'")["n"],
            "mines": q1("SELECT COALESCE(SUM(bet),0)-COALESCE(SUM(payout),0) n FROM mines WHERE status!='live'")["n"],
            "plinko": q1("SELECT COALESCE(SUM(bet),0)-COALESCE(SUM(payout),0) n FROM plinko")["n"]}


@app.get("/img/{size}")
def img(size: int, g: str, m: str):
    if size not in THUMB_SIZES or m not in MODELS.get(g, {}): raise HTTPException(404)
    path = model_thumb(g, m, size)
    if not path: raise HTTPException(404)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/admin")
def admin_page(): return FileResponse("static/admin.html")

@app.get("/")
def index(): return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
