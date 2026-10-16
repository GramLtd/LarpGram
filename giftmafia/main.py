import asyncio, functools, hashlib, shutil, subprocess, threading, hmac, io, json, math, os, random, re, secrets, sqlite3, time, urllib.parse, urllib.request
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InlineQueryResultPhoto,
                           InputTextMessageContent, LabeledPrice, WebAppInfo)
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from concurrent.futures import ThreadPoolExecutor
import story as storygen

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
FREE_NFT_CHANCE = 3  # % шанс NFT в бесплатном «Подарке дня»
ECONOMY_VERSION = "4"  # поменяйте, чтобы при старте пересобрать кейсы и призы (правки в админке сбросятся)
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
TON_STARS = 90  # ⭐ за 1 TON; обновляется раз в сутки по курсу TON (CoinGecko) и STAR_USD
STAR_USD = 0.015  # сколько стоит 1 звезда в долларах (средняя цена покупки)
MARKET_EVERY = 24 * 3600  # как часто обновлять цены с Portals
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

MODELS = {g: dict((m, p) for m, p in c["models"]) for g, c in CATALOG.items()}

# ---------- цены моделей ----------
# У каждой модели своя цена. Порядок: ручная цена из админки (вкладка «Цены») -> формула.
# Формула примерная: самая частая модель коллекции стоит как флор, более редкие дороже по кривой,
# модели с «дорогими» словами в названии (Gold, Midas, Black...) получают наценку, плюс небольшой
# стабильный разброс, чтобы модели одинаковой редкости не стоили одинаково. Точные цены задавайте в админке.
RARITY_POWER = 0.7     # крутизна наценки за редкость
MAX_MODEL_MULT = 10.0  # самая дорогая модель максимум во столько раз дороже флора
PREMIUM_WORDS = {"midas": 1.6, "gold": 1.35, "golden": 1.35, "diamond": 1.35, "platinum": 1.3, "rainbow": 1.3, "black": 1.25,
                 "onyx": 1.25, "galaxy": 1.25, "cosmic": 1.25, "noir": 1.2, "ruby": 1.15, "emerald": 1.15, "sapphire": 1.15,
                 "crystal": 1.15, "neon": 1.15, "silver": 1.1}
OVR = {}  # (коллекция, модель) -> ⭐, ручные цены из админки
MARKET = {}  # (коллекция, модель) -> флор модели в TON с Portals
CFLOOR = {}  # коллекция -> флор коллекции в TON с Portals


def _jitter(gift, model):  # стабильный разброс 0.92..1.22 (одинаковый при каждом запуске)
    return 0.92 + 0.3 * int(hashlib.md5(f"{gift}/{model}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


@functools.lru_cache(maxsize=None)
def formula_value(gift, model):
    perms = MODELS[gift]; common = max(perms.values()) or 1
    rarity = (common / max(perms[model], 1)) ** RARITY_POWER
    word = max([PREMIUM_WORDS[w] for w in re.findall(r"[a-z]+", model.lower()) if w in PREMIUM_WORDS], default=1.0)
    f = floor_stars(gift)
    return max(f, round(f * min(MAX_MODEL_MULT, rarity * word * _jitter(gift, model))))

def model_img(gift, model, size=256):  # лёгкое превью webp с нашего сервера, см. /img
    return f"/img/{size}?" + urllib.parse.urlencode({"g": gift, "m": model})

def nft_value(gift, model):
    if model not in MODELS.get(gift, {}): raise HTTPException(404, "Нет такой модели")
    if (gift, model) in OVR: return OVR[(gift, model)]
    ton = MARKET.get((gift, model))
    return round(ton * TON_STARS) if ton else formula_value(gift, model)

def floor_stars(gift): return round((CFLOOR.get(gift) or FLOORS.get(gift, DEFAULT_FLOOR)) * TON_STARS)

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
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, target TEXT DEFAULT '', reward INT DEFAULT 3, active INT DEFAULT 1, created INT);
CREATE TABLE IF NOT EXISTS task_done(user_id INT, task_id INT, created INT, PRIMARY KEY(user_id, task_id));
CREATE TABLE IF NOT EXISTS bot_started(user_id INTEGER PRIMARY KEY, created INT);
CREATE TABLE IF NOT EXISTS nick(user_id INTEGER PRIMARY KEY, started INT DEFAULT 0, claims INT DEFAULT 0, earned INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS market(gift TEXT, model TEXT, ton REAL, PRIMARY KEY(gift, model));
CREATE TABLE IF NOT EXISTS model_prices(gift TEXT, model TEXT, stars INT, PRIMARY KEY(gift, model));
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


OVR.update({(r["gift"], r["model"]): r["stars"] for r in db.execute("SELECT * FROM model_prices")})
for r in db.execute("SELECT * FROM market"):
    if r["model"]: MARKET[(r["gift"], r["model"])] = r["ton"]
    else: CFLOOR[r["gift"]] = r["ton"]
_ts = db.execute("SELECT v FROM meta WHERE k='ton_stars'").fetchone()
if _ts: TON_STARS = float(_ts["v"])

# ---------- настройки (правятся в админке) ----------
SETTINGS_DEFAULT = {
    "free_channel": "@GiftMafiaNFT",           # условие «Подарка дня»: подписка на канал (пусто = без условия)
    "nick_tag": "@GiftMafiaRobot",             # что поставить в имя/фамилию
    "nick_bio": "под защитой @GiftMafiaRobot",  # что поставить в описание (проверяется наличие nick_tag)
    "nick_rewards": "10,20,60,120",            # ⭐ в день для уровней Telegram 0 / 1-4 / 5-9 / 10+
}
NICK_HOLD, NICK_WINDOW = 24 * 3600, 10 * 3600  # держать 24 ч, потом 10 ч на сбор награды


def setting(k):
    r = q1("SELECT v FROM meta WHERE k=?", "set:" + k)
    return r["v"] if r else SETTINGS_DEFAULT[k]


def chat_ref(s):
    """'https://t.me/x', 't.me/x', '@x' -> ('@x', 'https://t.me/x')."""
    s = (s or "").strip()
    m = re.search(r"(?:t\.me/|@)([A-Za-z0-9_]{4,})", s) or re.fullmatch(r"([A-Za-z0-9_]{4,})", s)
    return (f"@{m.group(1)}", f"https://t.me/{m.group(1)}") if m else ("", "")


if not q1("SELECT 1 FROM meta WHERE k='tasks_seeded'"):  # задания для примера
    for kind, title, target in [("channel", "Подпишитесь на канал GiftMafia", "https://t.me/GiftMafiaNFT"),
                                ("bot", "Запустите бота", ""), ("story", "Выложите сторис с ботом", "")]:
        run("INSERT INTO tasks(kind,title,target,reward,created) VALUES(?,?,?,?,?)", kind, title, target, 3, int(time.time()))
    run("INSERT OR REPLACE INTO meta(k,v) VALUES('tasks_seeded','1')")


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


def build_cases(force=False):
    """Кейсы собираются из каталога: цена «красивая», у каждого кейса есть дешёвые призы, призы около цены и джекпоты.
    Веса подбираются так, чтобы средний возврат был CASE_RTP. Потом цены и веса можно править в админке."""
    if not force and (q1("SELECT v FROM meta WHERE k='economy'") or {}).get("v") == ECONOMY_VERSION: return
    run("DELETE FROM prizes"); run("DELETE FROM cases")
    rng = random.Random(11)
    C = []  # (id, title, price, cat, items, rtp)
    cheapest, seen = [], set()  # 8 самых дешёвых моделей разных подарков
    for v, g, m in sorted((nft_value(g, m), g, m) for g in CATALOG for m in MODELS[g]):
        if g not in seen: seen.add(g); cheapest.append(nft_item(g, m))
        if len(cheapest) == 8: break
    C.append((1, "Подарок дня", 0, "free", [stars_item(n) for n in (1, 2, 3, 5, 10, 25)] + cheapest, None))
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
        if cat == "free":  # звёзды 97%, NFT 3% поровну
            nft = [it for it in items if it["kind"] == "nft"]
            ws = [30, 25, 18, 13, 8, 3] + [FREE_NFT_CHANCE / len(nft)] * len(nft)
        elif cat == "fifty":  # честные 50/50: проигрыш - звёзды, выигрыш - NFT около x1.3
            win = items[0]; lose = max(1, round(2 * CASE_RTP * price - win["stars"]))
            items, ws = [stars_item(lose), win], [50, 50]
        else:
            ws = solve_weights([it["stars"] for it in items], price * rtp)
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
    w = q1("SELECT * FROM wins WHERE id=?", wid)
    if w["kind"] == "nft":
        w["story_url"] = story_url(wid)  # видео для «Выложить в историю», готовим заранее
        _story_pool.submit(lambda: make_story(dict(w), "mp4" if storygen.has_ffmpeg() else "jpg"))
    return w


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


# ---------- сторис и баннер ----------
STORY_DIR = "static/cache/stories"; os.makedirs(STORY_DIR, exist_ok=True)
_story_pool = ThreadPoolExecutor(max_workers=1)
_story_locks = {}


def _tier(gift, model):
    pm = MODELS.get(gift, {}).get(model, 30)
    return 3 if pm <= 5 else 2 if pm <= 10 else 1 if pm <= 20 else 0


def make_story(w, ext):
    """Готовит видео (.mp4) или картинку (.jpg) сторис для выигрыша и возвращает путь к файлу."""
    path = f"{STORY_DIR}/{w['id']}_{story_sig(w['id'])}.{ext}"
    with _story_locks.setdefault(w["id"], threading.Lock()):
        if os.path.exists(path): return path
        center = model_png(w["gift"], w["model"]) if w["gift"] else ""
        if not center: raise HTTPException(404)
        ps = q("SELECT gift,model FROM prizes WHERE kind='nft' AND case_id=? AND NOT (gift=? AND model=?) ORDER BY RANDOM() LIMIT 4", w["case_id"], w["gift"], w["model"])
        if len(ps) < 2: ps = q("SELECT DISTINCT gift,model FROM prizes WHERE kind='nft' ORDER BY RANDOM() LIMIT 4")
        sides = [x for x in (model_png(p["gift"], p["model"]) for p in ps) if x] or [center]
        st = storygen.Story(center, sides, w["gift"], w["model"], w["value"], BOT_USERNAME, _tier(w["gift"], w["model"]))
        tmp = f"{path}.tmp.{ext}"
        st.video(tmp) if ext == "mp4" else st.image(tmp)
        os.replace(tmp, path)
        return path


def make_banner():  # баннер 1280x720 для /start и приглашений
    W, H = 1280, 720
    base = Image.new("RGBA", (W, H)); d = ImageDraw.Draw(base)
    top, bot = (35, 26, 86), (12, 13, 34)
    for y in range(H): d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * y / H) for i in range(3)))
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0)); rd = ImageDraw.Draw(rays)
    for i in range(24):
        a, b = math.radians(i * 15), math.radians(i * 15 + 7)
        rd.polygon([(1030, 380), (1030 + 1500 * math.cos(a), 380 + 1500 * math.sin(a)), (1030 + 1500 * math.cos(b), 380 + 1500 * math.sin(b))], fill=(122, 98, 255, 45))
    base.alpha_composite(rays)
    base.paste((139, 92, 255, 255), (0, 0), glow(W, H, 1030, 380, 280, 120))
    ub = lambda s: ImageFont.truetype("static/fonts/Unbounded-ExtraBold.ttf", s)
    mr = lambda s: ImageFont.truetype("static/fonts/Manrope-Bold.ttf", s)
    d = ImageDraw.Draw(base)
    d.text((80, 200), "Gift", font=ub(92), fill="#ffffff", anchor="ls")
    d.text((80 + d.textlength("Gift", font=ub(92)), 200), "Mafia", font=ub(92), fill="#ffc83d", anchor="ls")
    for k, line in enumerate(["NFT-кейсы Telegram", "Мины · Апгрейды · Плинко", "Подарок дня — бесплатно"]):
        d.text((84, 290 + k * 58), line, font=mr(42), fill="#d6d8f5" if k else "#ffffff", anchor="ls")
    d.rounded_rectangle((80, 520, 420, 610), 45, fill="#6c4dff")
    d.text((250, 565), "Играть", font=ub(40), fill="#ffffff", anchor="mm")
    pics = [("Plush Pepe", None), ("Durov's Cap", None), ("Precious Peach", None)]
    for (g, _), (box, cx, cy) in zip(pics, [(210, 880, 200), (190, 1150, 545), (380, 1030, 380)]):
        if g in CATALOG:
            img = model_png(g, sorted(CATALOG[g]["models"], key=lambda x: x[1])[0][0])
            if img: put_nft(base, img, box, cx, cy)
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
def story_url(wid): return f"{WEBAPP_URL}/story/{wid}/{story_sig(wid)}.{'mp4' if storygen.has_ffmpeg() else 'jpg'}"


def admin(x_admin: str = Header("")):
    if not hmac.compare_digest(x_admin, ADMIN_TOKEN): raise HTTPException(401, "admin only")


def own_win(wid, uid):
    w = q1("SELECT * FROM wins WHERE id=? AND user_id=?", wid, uid)
    if not w: raise HTTPException(404, "нет такого выигрыша")
    return w


# ---------- bot ----------
@dp.message(CommandStart())
async def start(m):
    run("INSERT OR IGNORE INTO bot_started(user_id,created) VALUES(?,?)", m.from_user.id, int(time.time()))
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
    mk = asyncio.create_task(market_loop())
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
            "plinko": PLINKO, "plinko_max": PLINKO_MAX_BET,
            "free_channel": chat_ref(setting("free_channel")), "tasks": user_tasks(uid), "nick": nick_state(uid), "upgrade_max": UPGRADE_MAX_CHANCE}


CATALOG_CACHE = {}


@app.get("/api/catalog")
def catalog():
    """Все коллекции с флором; модели и редкость — в /static/gifts.json."""
    if not CATALOG_CACHE:
        CATALOG_CACHE.update(ton_stars=TON_STARS, floors_ton={g: FLOORS.get(g, DEFAULT_FLOOR) for g in CATALOG},
                             prices={g: [nft_value(g, m) for m, _ in c["models"]] for g, c in CATALOG.items()})
    return CATALOG_CACHE


async def is_member(chat, uid):
    """True/False, или None если бот не может проверить (не админ канала)."""
    try:
        m = await bot.get_chat_member(chat, uid)
        return m.status in ("member", "administrator", "creator") or getattr(m, "is_member", False)
    except Exception:
        return None


@app.post("/api/free")
async def free(uid: int = Depends(auth)):
    ch, url = chat_ref(setting("free_channel"))
    if ch and await is_member(ch, uid) is False: raise HTTPException(400, f"Подпишитесь на канал {ch}, чтобы открыть подарок дня")
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


@app.get("/story/{wid}/{name}")
def story_file(wid: int, name: str):
    sig, _, ext = name.partition(".")
    w = q1("SELECT * FROM wins WHERE id=?", wid)
    if ext not in ("mp4", "jpg") or not w or not hmac.compare_digest(sig, story_sig(wid)): raise HTTPException(404)
    if ext == "mp4" and not storygen.has_ffmpeg(): raise HTTPException(404)
    return FileResponse(make_story(w, ext), media_type="video/mp4" if ext == "mp4" else "image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.post("/api/win/{wid}/story")
def story(wid: int, uid: int = Depends(auth)):
    w = own_win(wid, uid)
    if w["status"] == "locked" and not w["story_at"]: run("UPDATE wins SET story_at=? WHERE id=?", int(time.time()), wid)
    return {"ok": True}


INVITE_TEXT = ("🎁 <b>GiftMafia — NFT-подарки Telegram</b>\n\n"
               "📦 Кейсы с настоящими NFT\n"
               "💣 Мины и 🚀 апгрейды\n"
               "🎯 Плинко\n"
               "🎉 Подарок дня — бесплатно\n"
               "⭐ Звёзды за задания\n\n"
               "👇 Заходи по моей ссылке")


@app.post("/api/invite/prepare")
async def invite_prepare(uid: int = Depends(auth)):
    """Готовое сообщение-приглашение: баннер, текст с эмодзи и кнопка с реферальной ссылкой."""
    link = f"https://t.me/{BOT_USERNAME}?startapp=r{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Открыть GiftMafia", url=link, style="primary")]])
    banner = f"{WEBAPP_URL}/static/banner.jpg?v={int(os.path.getmtime('static/banner.jpg')) if os.path.exists('static/banner.jpg') else 0}"
    res = InlineQueryResultPhoto(id=f"inv{uid}", photo_url=banner, thumbnail_url=banner, photo_width=1280, photo_height=720,
                                 caption=INVITE_TEXT, parse_mode="HTML", reply_markup=kb)
    pm = await bot.save_prepared_inline_message(user_id=uid, result=res, allow_user_chats=True, allow_group_chats=True, allow_channel_chats=True)
    return {"id": pm.id, "link": link}


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


# ---------- задания ----------
def user_tasks(uid):
    done = {r["task_id"] for r in q("SELECT task_id FROM task_done WHERE user_id=?", uid)}
    out = []
    for t in q("SELECT * FROM tasks WHERE active=1 ORDER BY id"):
        ch, url = chat_ref(t["target"]) if t["kind"] == "channel" else ("", t["target"])
        out.append({"id": t["id"], "kind": t["kind"], "title": t["title"], "reward": t["reward"], "url": url, "chat": ch, "done": t["id"] in done})
    return out


@app.post("/api/task/{tid}/check")
async def task_check(tid: int, uid: int = Depends(auth)):
    t = q1("SELECT * FROM tasks WHERE id=? AND active=1", tid)
    if not t: raise HTTPException(404, "Задание не найдено")
    if q1("SELECT 1 FROM task_done WHERE user_id=? AND task_id=?", uid, tid): raise HTTPException(400, "Задание уже выполнено")
    if t["kind"] == "channel":
        ok = await is_member(chat_ref(t["target"])[0], uid)
        if ok is None: raise HTTPException(400, "Проверка недоступна: бот должен быть админом канала")
        if not ok: raise HTTPException(400, "Вы ещё не подписались на канал")
    elif t["kind"] == "bot":
        if not q1("SELECT 1 FROM bot_started WHERE user_id=?", uid): raise HTTPException(400, "Откройте бота и нажмите «Старт»")
    # story / link Telegram проверить не даёт: засчитываем после нажатия
    if changed("INSERT OR IGNORE INTO task_done(user_id,task_id,created) VALUES(?,?,?)", uid, tid, int(time.time())):
        credit(uid, t["reward"])
    return {"reward": t["reward"]}


# ---------- ник и описание ----------
def nick_rewards(): return [int(x) for x in setting("nick_rewards").split(",")][:4]


def nick_state(uid):
    n = q1("SELECT * FROM nick WHERE user_id=?", uid) or {"started": 0, "claims": 0, "earned": 0}
    now, st = int(time.time()), n["started"]
    if st and now > st + NICK_HOLD + NICK_WINDOW: st = 0  # не успел забрать - начинаем заново
    return {"tag": setting("nick_tag"), "bio": setting("nick_bio"), "rewards": nick_rewards(), "started": st,
            "ready_in": max(0, st + NICK_HOLD - now) if st else None, "window": NICK_WINDOW, "claims": n["claims"], "earned": n["earned"]}


async def nick_check(uid):
    """(ок, уровень, текст ошибки) - стоит ли тег в имени и описании."""
    tag = setting("nick_tag").lower().lstrip("@")
    try: c = await bot.get_chat(uid)
    except Exception: return False, 0, "Сначала запустите бота (/start), чтобы он мог проверить профиль"
    name = f"{c.first_name or ''} {c.last_name or ''}".lower()
    level = getattr(getattr(c, "rating", None), "level", 0) or 0
    if tag not in name: return False, level, f"Добавьте {setting('nick_tag')} в имя или фамилию"
    if tag not in (c.bio or "").lower(): return False, level, f"Добавьте «{setting('nick_bio')}» в описание профиля"
    return True, level, ""


def level_reward(level):
    r = nick_rewards()
    return r[0] if level <= 0 else r[1] if level <= 4 else r[2] if level <= 9 else r[3]


@app.post("/api/nick/start")
async def nick_start(uid: int = Depends(auth)):
    ok, level, err = await nick_check(uid)
    if not ok: raise HTTPException(400, err)
    st = nick_state(uid)
    if not st["started"]:
        run("INSERT INTO nick(user_id,started) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET started=excluded.started", uid, int(time.time()))
    return nick_state(uid)


@app.post("/api/nick/claim")
async def nick_claim(uid: int = Depends(auth)):
    st = nick_state(uid)
    if not st["started"]: raise HTTPException(400, "Сначала выполните этап 1")
    if st["ready_in"]: raise HTTPException(400, "Награда ещё не готова")
    ok, level, err = await nick_check(uid)
    if not ok:
        run("UPDATE nick SET started=0 WHERE user_id=?", uid)
        raise HTTPException(400, err + ". Отсчёт начнётся заново")
    reward = level_reward(level)
    if changed("UPDATE nick SET started=?, claims=claims+1, earned=earned+? WHERE user_id=? AND started=?", int(time.time()), reward, uid, st["started"]):
        credit(uid, reward)  # новый суточный круг начинается сразу
    return {"reward": reward, "level": level, "nick": nick_state(uid)}


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


@app.get("/api/admin/models", dependencies=[Depends(admin)])
def a_models(q: str = "", own: int = 0):
    q = q.strip().lower(); out = []
    for g, c in CATALOG.items():
        for m, pm in c["models"]:
            if own and (g, m) not in OVR: continue
            if q and q not in f"{g} {m}".lower(): continue
            mk = MARKET.get((g, m))
            out.append({"gift": g, "model": m, "perm": pm, "formula": formula_value(g, m), "price": OVR.get((g, m)),
                        "market": round(mk * TON_STARS) if mk else None, "market_ton": mk, "img": model_img(g, m, 128)})
            if len(out) >= 80: return {"items": out, "more": True, "own": len(OVR), "info": market_info()}
    return {"items": out, "more": False, "own": len(OVR), "info": market_info()}


@app.post("/api/admin/model_price", dependencies=[Depends(admin)])
def a_model_price(b: dict):
    g, m = b.get("gift", ""), b.get("model", "")
    if m not in MODELS.get(g, {}): raise HTTPException(404, "Нет такой модели")
    stars = int(b.get("stars") or 0)
    if stars > 0: run("INSERT OR REPLACE INTO model_prices(gift,model,stars) VALUES(?,?,?)", g, m, stars); OVR[(g, m)] = stars
    else: run("DELETE FROM model_prices WHERE gift=? AND model=?", g, m); OVR.pop((g, m), None)
    v = nft_value(g, m)
    run("UPDATE prizes SET stars=? WHERE kind='nft' AND gift=? AND model=?", v, g, m)
    CATALOG_CACHE.clear()
    return {"price": v}


def rebalance_case(cid):
    """Подогнать шансы кейса под CASE_RTP. Возвращает текст ошибки или ''."""
    c = q1("SELECT * FROM cases WHERE id=?", cid)
    if not c or not c["price"]: return "Только для платных кейсов"
    ps = q("SELECT * FROM prizes WHERE case_id=?", cid)
    if c["cat"] == "fifty" and len(ps) == 2:
        lose = [p for p in ps if p["kind"] == "stars"]; win = [p for p in ps if p["kind"] == "nft"]
        if lose and win:
            if not c["price"] * 1.1 <= win[0]["stars"] <= c["price"] * 1.6:  # NFT подорожал/подешевел - берём другой около x1.3
                it = near(c["price"] * 1.3, random.Random(cid), spread=0.05)
                run("UPDATE prizes SET name=?,gift=?,model=?,img=?,stars=? WHERE id=?", it["name"], it["gift"], it["model"], it["img"], it["stars"], win[0]["id"])
                win[0]["stars"] = it["stars"]
            run("UPDATE prizes SET stars=? WHERE id=?", max(1, round(2 * CASE_RTP * c["price"] - win[0]["stars"])), lose[0]["id"])
        return ""
    vals = [p["stars"] for p in ps]
    if not vals or min(vals) >= c["price"] * CASE_RTP or max(vals) <= c["price"] * CASE_RTP:
        return "Нельзя подогнать: нужны призы дешевле и дороже цены кейса"
    for p, w in zip(ps, solve_weights(vals, c["price"] * CASE_RTP)): run("UPDATE prizes SET weight=? WHERE id=?", w, p["id"])
    return ""


@app.post("/api/admin/case/{cid}/rebalance", dependencies=[Depends(admin)])
def a_rebalance(cid: int):
    err = rebalance_case(cid)
    if err: raise HTTPException(400, err)
    return {"ok": True}


# ---------- цены с рынка (Portals) ----------
PORTALS = "https://portal-market.com/api"
_market_lock = threading.Lock()


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 giftmafia"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)


def _norm(name): return re.sub(r"[^a-z0-9]", "", name.lower().replace("’", "'"))


def refresh_market():
    """Флор каждой коллекции и модели с Portals, курс TON->⭐, затем пересчёт цен призов и шансов кейсов."""
    global TON_STARS
    with _market_lock:
        try:
            usd = _get_json("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd")["the-open-network"]["usd"]
            ton_stars = round(usd / STAR_USD, 1)
        except Exception: ton_stars = TON_STARS
        ours = {_norm(g): g for g in CATALOG}
        cols, off = [], 0
        while True:
            page = _get_json(f"{PORTALS}/collections?limit=100&offset={off}")["collections"]
            cols += page; off += 100
            if len(page) < 100 or off > 2000: break
        cfloor, short = {}, {}
        for c in cols:
            g = ours.get(_norm(c["name"]))
            if not g: continue
            short[c["short_name"]] = g
            if c.get("floor_price"): cfloor[g] = float(c["floor_price"])
        market, names = {}, list(short)
        for i in range(0, len(names), 10):
            data = _get_json(f"{PORTALS}/collections/filters?short_names={','.join(names[i:i + 10])}").get("collections", {})
            for sn, v in data.items():
                g = short.get(sn)
                if not g: continue
                mods = {_norm(m): m for m in MODELS[g]}
                for m in v.get("models", []):
                    our = mods.get(_norm(m["name"]))
                    if our and m.get("floor_price"): market[(g, our)] = float(m["floor_price"])
            time.sleep(0.3)
        if not cfloor: return {"error": "Portals не ответил, цены не изменены"}
        db.execute("DELETE FROM market")
        db.executemany("INSERT INTO market(gift,model,ton) VALUES(?,?,?)", [(g, "", t) for g, t in cfloor.items()] + [(g, m, t) for (g, m), t in market.items()])
        for k, v in (("ton_stars", ton_stars), ("market_updated", int(time.time()))):
            db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))
        db.commit()
        TON_STARS = ton_stars; CFLOOR.clear(); CFLOOR.update(cfloor); MARKET.clear(); MARKET.update(market)
        formula_value.cache_clear(); CATALOG_CACHE.clear()
        for p in q("SELECT id,gift,model FROM prizes WHERE kind='nft'"):
            try: run("UPDATE prizes SET stars=?,img=? WHERE id=?", nft_value(p["gift"], p["model"]), model_img(p["gift"], p["model"]), p["id"])
            except HTTPException: pass
        if (q1("SELECT v FROM meta WHERE k='economy_market'") or {}).get("v") != ECONOMY_VERSION:
            build_cases(force=True)  # первый раз с рыночными ценами - пересобрать кейсы (цены кейсов от рынка)
            run("INSERT OR REPLACE INTO meta(k,v) VALUES('economy_market',?)", ECONOMY_VERSION)
        bad = [c["title"] for c in q("SELECT id,title FROM cases WHERE price>0") if rebalance_case(c["id"])]
        return {"ton_stars": ton_stars, "collections": len(cfloor), "models": len(market), "cases_not_rebalanced": bad}


def market_info():
    r = q1("SELECT v FROM meta WHERE k='market_updated'")
    return {"ton_stars": TON_STARS, "star_usd": STAR_USD, "updated": int(r["v"]) if r else 0, "models": len(MARKET), "collections": len(CFLOOR)}


async def market_loop():
    while True:
        try:
            if time.time() - market_info()["updated"] > MARKET_EVERY - 600:
                print("market:", await asyncio.to_thread(refresh_market))
        except Exception as e: print("market error:", e)
        await asyncio.sleep(3600)


@app.post("/api/admin/market/refresh", dependencies=[Depends(admin)])
async def a_market_refresh():
    try: res = await asyncio.to_thread(refresh_market)
    except Exception as e: raise HTTPException(502, f"Не удалось обновить: {e}")
    return {**res, **market_info()}


@app.get("/api/admin/tasks", dependencies=[Depends(admin)])
def a_tasks():
    ts = q("SELECT t.*, (SELECT COUNT(*) FROM task_done d WHERE d.task_id=t.id) done FROM tasks t ORDER BY id")
    return {"tasks": ts, "settings": {k: setting(k) for k in SETTINGS_DEFAULT}}


@app.post("/api/admin/task", dependencies=[Depends(admin)])
def a_task_add(b: dict):
    kind = b.get("kind", "link")
    if kind not in ("channel", "bot", "story", "link"): raise HTTPException(400, "Неверный тип")
    title = (b.get("title") or "").strip()
    if not title: raise HTTPException(400, "Введите название")
    target = (b.get("target") or "").strip()
    if kind == "channel" and not chat_ref(target)[0]: raise HTTPException(400, "Укажите канал: https://t.me/имя или @имя")
    if kind == "link" and not target.startswith(("https://", "tg://")): raise HTTPException(400, "Укажите ссылку https://...")
    run("INSERT INTO tasks(kind,title,target,reward,created) VALUES(?,?,?,?,?)", kind, title, target, max(1, int(b.get("reward") or 3)), int(time.time()))
    return {"ok": True}


@app.patch("/api/admin/task/{tid}", dependencies=[Depends(admin)])
def a_task_edit(tid: int, b: dict):
    if "active" in b: run("UPDATE tasks SET active=? WHERE id=?", 1 if b["active"] else 0, tid)
    if "reward" in b: run("UPDATE tasks SET reward=? WHERE id=?", max(1, int(b["reward"])), tid)
    return {"ok": True}


@app.delete("/api/admin/task/{tid}", dependencies=[Depends(admin)])
def a_task_del(tid: int):
    run("DELETE FROM tasks WHERE id=?", tid); return {"ok": True}


@app.post("/api/admin/settings", dependencies=[Depends(admin)])
def a_settings(b: dict):
    for k, v in b.items():
        if k not in SETTINGS_DEFAULT: continue
        v = str(v).strip()
        if k == "nick_rewards" and not re.fullmatch(r"\d+,\d+,\d+,\d+", v.replace(" ", "")): raise HTTPException(400, "Награды: 4 числа через запятую")
        if k == "free_channel" and v and not chat_ref(v)[0]: raise HTTPException(400, "Канал: https://t.me/имя или @имя, пусто - без условия")
        run("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", "set:" + k, v.replace(" ", "") if k == "nick_rewards" else v)
    return {k: setting(k) for k in SETTINGS_DEFAULT}


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
