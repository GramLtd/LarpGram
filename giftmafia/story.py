"""Графика в стиле мини-аппа: видео-сторис с выигрышем (720x1280, 7 с), баннер для /start и аватарка бота.
Всё рисуется Pillow, видео кодирует ffmpeg (без ffmpeg сторис - картинка того же дизайна)."""
import math, random, shutil, subprocess
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SECONDS = 720, 1280, 30, 7
FONTS = "static/fonts/"
BG = (18, 19, 41)
# цвета редкости как в мини-аппе (.t0-.t3): верх карточки, низ, полоса снизу
TIERS = [((45, 62, 120), (35, 42, 79), (79, 125, 255)), ((74, 53, 146), (44, 36, 87), (139, 108, 255)),
         ((122, 47, 127), (63, 32, 80), (224, 92, 226)), ((140, 44, 63), (74, 29, 43), (255, 90, 110))]
RAR = ["Обычная", "Редкая", "Эпическая", "Легендарная"]
GOLD = [(255, 224, 122), (243, 165, 20)]


def font(name, size): return ImageFont.truetype(FONTS + name, size)
def UB(s): return font("Unbounded-ExtraBold.ttf", s)
def MB(s): return font("Manrope-ExtraBold.ttf", s)
def MR(s): return font("Manrope-Bold.ttf", s)


def has_ffmpeg(): return shutil.which("ffmpeg") is not None


def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(t): return 1 - (1 - clamp(t)) ** 3
def ease_quint(t): return 1 - (1 - clamp(t)) ** 5
def ease_io(t): t = clamp(t); return t * t * (3 - 2 * t)
def ease_back(t, s=1.4): t = clamp(t) - 1; return t * t * ((s + 1) * t + s) + 1


# ---------- примитивы ----------
def vgrad(w, h, top, bot):
    """Вертикальный градиент RGBA."""
    col = Image.new("RGBA", (1, h))
    for y in range(h):
        k = y / max(1, h - 1); col.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)) + (255,))
    return col.resize((w, h))


def hgrad(w, h, a, b):
    row = Image.new("RGBA", (w, 1))
    for x in range(w):
        k = x / max(1, w - 1); row.putpixel((x, 0), tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)) + (255,))
    return row.resize((w, h))


def rmask(w, h, r, scale=3):
    m = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], r * scale, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def rounded(fill_img, r):
    out = fill_img.copy(); out.putalpha(ImageChops.multiply(out.getchannel("A"), rmask(*fill_img.size, r))); return out


def shadow(w, h, r, blur=26, alpha=150, pad=40):
    s = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle([pad, pad + 14, pad + w, pad + h + 14], r, fill=(0, 0, 0, alpha))
    return s.filter(ImageFilter.GaussianBlur(blur))


def glow(size, color, alpha=200, blur=None):
    g = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([size * .2, size * .2, size * .8, size * .8], fill=color + (alpha,))
    return g.filter(ImageFilter.GaussianBlur(blur or size // 7))


def card(w, h, r=36, top=(36, 38, 77), bot=(27, 28, 58), border=(255, 255, 255, 22), stripe=None):
    """Карточка как .card / .it в мини-аппе: градиент, тонкая рамка, цветная полоса снизу."""
    c = rounded(vgrad(w, h, top, bot), r)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0, 0, w - 1, h - 1], r, outline=border, width=2)
    if stripe:
        s = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(s).rectangle([0, h - 7, w, h], fill=stripe + (255,))
        s.putalpha(ImageChops.multiply(s.getchannel("A"), rmask(w, h, r))); c.alpha_composite(s)
    return c


def pill(text, f, pad_x=26, h=64, grad=((79, 123, 255), (139, 92, 255)), color="white", icon_w=0):
    tw = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=f))
    w = tw + pad_x * 2 + icon_w
    p = rounded(hgrad(w, h, *grad), h // 2)
    hl = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(hl).rounded_rectangle([2, 2, w - 3, h // 2], h // 2, fill=(255, 255, 255, 34))
    hl.putalpha(ImageChops.multiply(hl.getchannel("A"), rmask(w, h, h // 2))); p.alpha_composite(hl)
    ImageDraw.Draw(p).text((pad_x + icon_w + tw / 2, h / 2 + 1), text, font=f, fill=color, anchor="mm")
    return p


def glass(w, h, r, alpha=26):
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(g)
    d.rounded_rectangle([0, 0, w - 1, h - 1], r, fill=(255, 255, 255, alpha), outline=(255, 255, 255, 52), width=2)
    d.rounded_rectangle([3, 2, w - 4, h // 2], r, fill=(255, 255, 255, 14))
    return g


def star(d, cx, cy, r, fill=(255, 200, 61, 255)):
    pts = [(cx + (r if i % 2 == 0 else r * .47) * math.cos(-math.pi / 2 + i * math.pi / 5),
            cy + (r if i % 2 == 0 else r * .47) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]
    d.polygon(pts, fill=fill)
    d.polygon([(cx + (x - cx) * .5, cy + (y - cy) * .5 - r * .04) for x, y in pts], fill=(255, 246, 194, 120))


def txt(img, xy, s, f, fill, anchor="ls"):
    """Текст с прозрачностью (fill=(r,g,b,a)): ImageDraw.text альфу не смешивает, рисуем на слой."""
    if len(fill) == 4 and fill[3] < 255:
        if fill[3] <= 0: return
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); ImageDraw.Draw(layer).text(xy, s, font=f, fill=fill[:3] + (255,), anchor=anchor)
        layer.putalpha(layer.getchannel("A").point(lambda v: v * fill[3] // 255)); img.alpha_composite(layer)
    else: ImageDraw.Draw(img).text(xy, s, font=f, fill=fill, anchor=anchor)


def gold_text(img, xy, text, f, anchor="ls"):
    """Текст с золотым градиентом, как «Mafia» в логотипе."""
    m = Image.new("L", img.size, 0); ImageDraw.Draw(m).text(xy, text, font=f, fill=255, anchor=anchor)
    box = m.getbbox()
    if not box: return
    g = vgrad(box[2] - box[0], box[3] - box[1], *GOLD); layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); layer.paste(g, box[:2])
    layer.putalpha(m); img.alpha_composite(layer)


def logo(img, x, y, size, anchor_center=False, alpha=1.0):
    if alpha < 1:
        if alpha <= 0: return
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); logo(layer, x, y, size, anchor_center)
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha))); img.alpha_composite(layer); return
    f = UB(size); d = ImageDraw.Draw(img)
    w1, w2 = d.textlength("Gift", font=f), d.textlength("Mafia", font=f)
    if anchor_center: x -= (w1 + w2) / 2
    d.text((x, y), "Gift", font=f, fill="white", anchor="ls"); gold_text(img, (x + w1, y), "Mafia", f)


def fit(im, box):
    im = im.copy(); im.thumbnail((box, box), Image.LANCZOS); return im


def nft_shadow(im, blur=16, dy=14, a=0.55):
    s = Image.new("RGBA", (im.width + 80, im.height + 80), (0, 0, 0, 0))
    s.paste((0, 0, 0, 255), (40, 40 + dy), im.getchannel("A").point(lambda v: int(v * a)))
    return s.filter(ImageFilter.GaussianBlur(blur))


def put(base, im, cx, cy, alpha=1.0):
    if alpha < 1: im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    base.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def background(w, h, spots):
    """Тёмный фон мини-аппа с мягкими цветными пятнами: [(cx, cy, r, color, alpha)]."""
    bg = Image.new("RGBA", (w, h), BG + (255,))
    for cx, cy, r, c, a in spots:
        g = glow(r * 2, c, a, r // 3); bg.alpha_composite(g, (int(cx - r), int(cy - r)))
    return bg


# ---------- сторис ----------
class Story:
    def __init__(self, center_png, side_pngs, gift, model, value, bot, tier=1):
        self.tier = tier; self.c = TIERS[tier][2]
        self.gift, self.model, self.value, self.bot = gift, model, value, bot
        src = Image.open(center_png).convert("RGBA")
        self.big = fit(src, 380); self.big_sh = nft_shadow(self.big, 22, 22, .6)
        rnd = random.Random(f"{gift}{model}")
        sides = [Image.open(p).convert("RGBA") for p in (side_pngs or [center_png])]
        self.CW, self.CH, self.GAP = 196, 236, 18
        mk = lambda im, t: self._item(fit(im, 150), t)
        self.win_i = 16
        self.strip = [mk(rnd.choice(sides), rnd.choice([0, 0, 1, 1, 2, 3])) for _ in range(self.win_i)] + [mk(src, tier)] + \
                     [mk(rnd.choice(sides), rnd.choice([0, 1, 2])) for _ in range(3)]
        self._static()

    def _item(self, im, t):
        c1, c2, c3 = TIERS[t]
        it = card(self.CW, self.CH, 30, c1, c2, (255, 255, 255, 26), c3)
        it.alpha_composite(nft_shadow(im, 10, 8), (int(self.CW / 2 - im.width / 2 - 40), int(self.CH / 2 - 12 - im.height / 2 - 40)))
        it.alpha_composite(im, (int(self.CW / 2 - im.width / 2), int(self.CH / 2 - 12 - im.height / 2)))
        return it

    def _static(self):
        self.bg = background(W, H, [(W * .5, -60, 520, (91, 70, 212), 120), (W * .1, H * .55, 360, (79, 123, 255), 50), (W * .95, H * .75, 380, (139, 92, 255), 60)])
        self.halo = glow(760, self.c, 170)
        self.panel = card(W - 64, 330, 40)
        self.panel_sh = shadow(W - 64, 330, 40)
        self.ring = Image.new("RGBA", (self.CW + 16, self.CH + 16), (0, 0, 0, 0))
        ImageDraw.Draw(self.ring).rounded_rectangle([2, 2, self.CW + 13, self.CH + 13], 34, outline=(255, 255, 255, 255), width=5)
        self.ring_glow = glow(self.CW * 2, self.c, 230, 40)
        self.cta = pill("Забрать подарок", UB(34), 40, 96)
        self.cta_sh = shadow(self.cta.width, 96, 48, 24, 160)
        self.free = pill("Подарок дня — бесплатно", MB(26), 26, 54, ((32, 181, 107), (62, 224, 143)))
        self.top_glass = glass(W - 64, 92, 46)
        rar = RAR[self.tier]
        self.rar_pill = pill(rar, MB(24), 20, 46, (tuple(int(v * .55) for v in self.c), tuple(int(v * .35) for v in self.c)))
        vt = f"{self.value:,}".replace(",", " ")
        self.val_pill = glass(int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(vt, font=UB(40))) + 120, 78, 39, 34)
        d = ImageDraw.Draw(self.val_pill); d.text((32, 40), vt, font=UB(40), fill="white", anchor="lm")
        star(d, self.val_pill.width - 44, 38, 22)

    def frame(self, t):
        im = self.bg.copy(); d = ImageDraw.Draw(im, "RGBA")
        # шапка: логотип и @бот в стеклянной плашке
        a_top = ease_out(t / .6)
        tg = self.top_glass.copy(); tg.putalpha(tg.getchannel("A").point(lambda v: int(v * a_top)))
        im.alpha_composite(tg, (32, int(64 - 20 * (1 - a_top))))
        logo(im, 64, int(124 - 20 * (1 - a_top)), 40, alpha=a_top)
        txt(im, (W - 64, 112 - 20 * (1 - a_top)), f"@{self.bot}" if self.bot else "", MB(26), (159, 162, 204, int(255 * a_top)), "rs")
        # заголовок
        a = ease_out((t - .15) / .7)
        txt(im, (W / 2, 262 - 26 * (1 - a)), "Я выиграл!", UB(68), (255, 255, 255, int(255 * a)), "ms")
        txt(im, (W / 2, 318 - 26 * (1 - a)), "NFT-подарок в GiftMafia", MR(30), (159, 162, 204, int(255 * a)), "ms")
        spin_end, reveal = 3.0, 3.2
        k = ease_out((t - spin_end) / 1.1)  # переход от ленты к большому подарку
        # ореол за подарком
        if t > spin_end - .3:
            pulse = 0.9 + 0.1 * math.sin(t * 2.6)
            h = self.halo.copy(); h.putalpha(h.getchannel("A").point(lambda v: int(v * ease_io((t - spin_end + .3) / 1.2) * pulse)))
            im.alpha_composite(h, (int(W / 2 - 380), int(640 - 380)))
        # панель с лентой (как экран кейса)
        if k < 1:
            pa = 1 - ease_io(k / .8)
            py = 445 + 40 * (1 - ease_out((t - .25) / .8))
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            layer.alpha_composite(self.panel_sh, (32 - 40, int(py) - 40)); layer.alpha_composite(self.panel, (32, int(py)))
            pos = 2 + ease_quint((t - .4) / (spin_end - .4)) * (self.win_i - 2)  # какой элемент по центру
            step = self.CW + self.GAP; cy = py + 330 / 2; strip = Image.new("RGBA", (W - 64, 330), (0, 0, 0, 0))
            for i, it in enumerate(self.strip):
                dx = (i - pos) * step
                if abs(dx) > W / 2 + step: continue
                x = (W - 64) / 2 + dx
                if i == self.win_i and t > spin_end:
                    g = ease_out((t - spin_end) / .4)
                    rg = self.ring_glow.copy(); rg.putalpha(rg.getchannel("A").point(lambda v: int(v * g)))
                    strip.alpha_composite(rg, (int(x - rg.width / 2), int(165 - rg.height / 2)))
                    strip.alpha_composite(self.ring, (int(x - self.ring.width / 2), int(165 - self.ring.height / 2)))
                dim = 1.0 if t < spin_end or i == self.win_i else 1 - .6 * ease_out((t - spin_end) / .4)
                put(strip, it, x, 165, dim)
            mk = rmask(W - 64, 330, 40); strip.putalpha(ImageChops.multiply(strip.getchannel("A"), mk))
            layer.alpha_composite(strip, (32, int(py)))
            dl = ImageDraw.Draw(layer, "RGBA")  # указатели сверху и снизу
            for y, s in ((py + 4, 1), (py + 326, -1)):
                dl.polygon([(W / 2 - 16, y), (W / 2 + 16, y), (W / 2, y + 20 * s)], fill="white")
            if pa < 1: layer.putalpha(layer.getchannel("A").point(lambda v: int(v * pa)))
            im.alpha_composite(layer)
        # большой подарок
        if t > spin_end:
            sc = 0.5 + 0.5 * ease_back((t - spin_end) / .9)
            fl = 8 * math.sin((t - reveal) * 2.4) if t > reveal else 0
            big = self.big.resize((max(1, int(self.big.width * sc)), max(1, int(self.big.height * sc))), Image.LANCZOS)
            ba = ease_out((t - spin_end) / .5)
            sh = self.big_sh.resize((max(1, int(self.big_sh.width * sc)), max(1, int(self.big_sh.height * sc))), Image.LANCZOS)
            put(im, sh, W / 2, 640 + fl * .3, ba); put(im, big, W / 2, 610 + fl, ba)
            for j, (sx, sy, sr) in enumerate([(170, 470, 20), (560, 520, 15), (540, 760, 18), (190, 740, 13), (360, 400, 11)]):
                tw = 0.5 + 0.5 * math.sin(t * 3.4 + j * 1.9)
                s = Image.new("RGBA", (80, 80), (0, 0, 0, 0)); sd = ImageDraw.Draw(s); r = sr * (0.6 + 0.5 * tw)
                sd.polygon([(40, 40 - r), (40 + r * .22, 40 - r * .22), (40 + r, 40), (40 + r * .22, 40 + r * .22), (40, 40 + r),
                            (40 - r * .22, 40 + r * .22), (40 - r, 40), (40 - r * .22, 40 - r * .22)], fill=(255, 236, 170, int(230 * tw * ba)))
                im.alpha_composite(s, (sx - 40, sy - 40))
            # подписи
            a = ease_out((t - reveal - .1) / .6); dy = 24 * (1 - a); d = ImageDraw.Draw(im, "RGBA")
            txt(im, (W / 2, 880 + dy), self.gift, UB(46 if len(self.gift) < 16 else 38), (255, 255, 255, int(255 * a)), "ms")
            mw = d.textlength(self.model, font=MB(30)); total = mw + 16 + self.rar_pill.width; x0 = W / 2 - total / 2
            txt(im, (x0, 930 + dy), self.model, MB(30), (217, 218, 240, int(255 * a)), "lm")
            put(im, self.rar_pill, x0 + mw + 16 + self.rar_pill.width / 2, 930 + dy, a)
            a2 = ease_out((t - reveal - .3) / .6)
            put(im, self.val_pill, W / 2, 1012 + 20 * (1 - a2), a2)
        # кнопка и бейдж внизу
        a = ease_out((t - .5) / .8); by = 1132 + 30 * (1 - a)
        put(im, self.cta_sh, W / 2, by + 6, a)
        cta = self.cta.copy()
        sh_x = ((t * 0.55) % 1.6 - 0.3) * cta.width  # блик пробегает по кнопке
        bl = Image.new("RGBA", cta.size, (0, 0, 0, 0)); ImageDraw.Draw(bl).polygon([(sh_x, 0), (sh_x + 70, 0), (sh_x + 20, cta.height), (sh_x - 50, cta.height)], fill=(255, 255, 255, 70))
        bl = bl.filter(ImageFilter.GaussianBlur(8)); bl.putalpha(ImageChops.multiply(bl.getchannel("A"), cta.getchannel("A"))); cta.alpha_composite(bl)
        put(im, cta, W / 2, by, a)
        put(im, self.free, W / 2, by + 92, ease_out((t - .8) / .8))
        return im.convert("RGB")

    def video(self, out):
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                              "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                             stdin=subprocess.PIPE)
        for i in range(FPS * SECONDS): p.stdin.write(self.frame(i / FPS).tobytes())
        p.stdin.close()
        if p.wait() != 0: raise RuntimeError("ffmpeg failed")

    def image(self, out):
        self.frame(5.0).save(out, "JPEG", quality=90)


# ---------- баннер 1280x720 (/start и приглашения) ----------
def banner(out, cards):
    """cards: [(png, название, подпись цены, цвет свечения, зелёная ли цена)] - 3 карточки кейсов как в мини-аппе."""
    BW, BH = 1280, 720
    im = background(BW, BH, [(260, -40, 460, (91, 70, 212), 130), (1000, 380, 420, (139, 92, 255), 80), (80, 700, 300, (79, 123, 255), 45)])
    d = ImageDraw.Draw(im, "RGBA")
    logo(im, 80, 196, 88)
    d.text((84, 270), "NFT-кейсы с подарками Telegram", font=MB(38), fill="white", anchor="ls")
    d.text((84, 318), "Открывай кейсы, играй и выводи NFT", font=MR(30), fill=(159, 162, 204), anchor="ls")
    x = 80
    for t in ("Кейсы", "Мины", "Апгрейд", "Плинко"):  # стеклянные чипсы как фильтры в мини-аппе
        f = MB(26); w = int(d.textlength(t, font=f)) + 44
        im.alpha_composite(glass(w, 54, 27, 22), (x, 366)); ImageDraw.Draw(im, "RGBA").text((x + w / 2, 394), t, font=f, fill=(217, 218, 240), anchor="mm"); x += w + 10
    b = pill("Играть", UB(36), 52, 92)
    im.alpha_composite(shadow(b.width, 92, 46, 22, 150), (80 - 40, 470 - 40)); im.alpha_composite(b, (80, 470))
    fr = pill("Подарок дня бесплатно", MB(26), 24, 56, ((32, 181, 107), (62, 224, 143)))
    im.alpha_composite(fr, (80 + b.width + 18, 488))
    # карточки кейсов справа: центральная крупнее, боковые ниже и повернуты
    spots = [(888, 400, 220, -7, .84), (1176, 410, 220, 7, .84), (1030, 360, 250, 0, 1.0)]
    order = [0, 1, 2]
    for (png, title, price, col, green), (cx, cy, cw, rot, sc) in zip([cards[i] for i in order], spots):
        ch = cw - 20 + 124
        c = card(cw, ch, 34)
        cov_w = cw - 20
        cov = rounded(vgrad(cov_w, cov_w, (42, 44, 72), (20, 21, 42)), 26)
        cov.alpha_composite(glow(cov_w, col, 190), (0, 0))
        if png:
            n = fit(Image.open(png).convert("RGBA"), int(cov_w * .72))
            cov.alpha_composite(nft_shadow(n, 10, 10), (int(cov_w / 2 - n.width / 2 - 40), int(cov_w / 2 - n.height / 2 - 40)))
            cov.alpha_composite(n, (int(cov_w / 2 - n.width / 2), int(cov_w / 2 - n.height / 2)))
        c.alpha_composite(cov, (10, 10))
        cd = ImageDraw.Draw(c); cd.text((22, cov_w + 52), title, font=MB(24), fill="white", anchor="ls")
        pp = pill(price, MB(22), 18, 42, ((32, 181, 107), (62, 224, 143)) if green else ((79, 123, 255), (139, 92, 255)), icon_w=0 if green else 30)
        if not green: star(ImageDraw.Draw(pp), 18 + 13, 21, 12)
        c.alpha_composite(pp, (18, cov_w + 64))
        full = Image.new("RGBA", (cw + 120, ch + 120), (0, 0, 0, 0)); full.alpha_composite(shadow(cw, ch, 34, 26, 170, 60), (0, 0)); full.alpha_composite(c, (60, 60))
        if sc != 1: full = full.resize((int(full.width * sc), int(full.height * sc)), Image.LANCZOS)
        if rot: full = full.rotate(rot, Image.BICUBIC, expand=True)
        im.alpha_composite(full, (int(cx - full.width / 2), int(cy - full.height / 2)))
    im.convert("RGB").save(out, quality=93)


# ---------- аватарка бота 640x640 ----------
def avatar(out, png):
    S = 640
    im = background(S, S, [(320, 300, 360, (108, 77, 255), 200), (120, 560, 220, (79, 123, 255), 90), (560, 80, 200, (224, 92, 226), 70)])
    d = ImageDraw.Draw(im, "RGBA")
    for r, a in ((262, 26), (214, 18)):  # тонкие кольца как у стеклянных кнопок
        d.ellipse([320 - r, 300 - r, 320 + r, 300 + r], outline=(255, 255, 255, a), width=3)
    if png:
        n = fit(Image.open(png).convert("RGBA"), 400)
        im.alpha_composite(nft_shadow(n, 18, 18, .6), (int(320 - n.width / 2 - 40), int(290 - n.height / 2 - 40)))
        im.alpha_composite(n, (int(320 - n.width / 2), int(290 - n.height / 2)))
    pl = pill("GiftMafia", UB(40), 34, 76, ((243, 165, 20), (255, 210, 90)), color=(58, 38, 0))
    im.alpha_composite(shadow(pl.width, 76, 38, 18, 160), (int(320 - pl.width / 2 - 40), 500 - 40)); im.alpha_composite(pl, (int(320 - pl.width / 2), 500))
    im.convert("RGB").save(out, "PNG")
