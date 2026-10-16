"""Обновляет static/gifts.json: все NFT-подарки Telegram и их модели с редкостью.
Данные: api.changes.tg (@GiftChanges). Запуск: python tools/fetch_gifts.py"""
import json, os, time, urllib.parse, urllib.request

API = "https://api.changes.tg"
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "gifts.json")


def get(path):
    for i in range(4):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "giftmafia/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
        except Exception:
            if i == 3: raise
            time.sleep(2 ** i)


def main():
    ids = {v: k for k, v in get("/ids").items()}
    out = []
    for name in get("/gifts"):
        models = get("/models/" + urllib.parse.quote(name) + "?sorted")
        out.append({"name": name, "id": ids.get(name, ""),
                    "models": [[m["name"], m["rarityPermille"]] for m in models]})
        print(name, len(models))
    with open(OUT, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("коллекций:", len(out), "моделей:", sum(len(g["models"]) for g in out))


if __name__ == "__main__": main()
