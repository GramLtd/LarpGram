"""Видео-сторис с выигрышем (720x1280, 7 с): лучи, «Я выиграл!», лента с подарком, уведомление и плашка «Забрать подарок!».
Кадры рисуются Pillow и кодируются ffmpeg. Без ffmpeg можно сделать картинку того же дизайна (render_image)."""
import math, random, shutil, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SECONDS = 720, 1280, 24, 7
FONTS = "static/fonts/"
TIER = ["#4f9dff", "#8b6cff", "#e05ce2", "#ff5a6e"]  # обычная / редкая / эпическая / легендарная


def font(name, size): return ImageFont.truetype(FONTS + name, size)


def has_ffmpeg(): return shutil.which("ffmpeg") is not None


def _rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _ease_out(t): return 1 - (1 - t) ** 3


def _back(t, s=1.6): t -= 1; return t * t * ((s + 1) * t + s) + 1


def _star(d, cx, cy, r, fill):
    pts = [(cx + (r if i % 2 == 0 else r * .45) * math.cos(-math.pi / 2 + i * math.pi / 5),
            cy + (r if i % 2 == 0 else r * .45) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]
    d.polygon(pts, fill=fill)


def _sparkle(d, cx, cy, r, fill):
    d.polygon([(cx, cy - r), (cx + r * .22, cy - r * .22), (cx + r, cy), (cx + r * .22, cy + r * .22),
               (cx, cy + r), (cx - r * .22, cy + r * .22), (cx - r, cy), (cx - r * .22, cy - r * .22)], fill=fill)


class Story:
    def __init__(self, center_png, side_pngs, gift, model, value, bot, tier=1):
        self.c = _rgb(TIER[tier])
        self.gift, self.model, self.value, self.bot = gift, model, value, bot
        self.big = Image.open(center_png).convert("RGBA"); self.big.thumbnail((360, 360), Image.LANCZOS)
        self.sides = []
        for p in side_pngs or [center_png]:
            im = Image.open(p).convert("RGBA"); im.thumbnail((250, 250), Image.LANCZOS); self.sides.append(im)
        rnd = random.Random(f"{gift}{model}")
        self.strip = [rnd.choice(self.sides) for _ in range(14)] + [self.big] + [rnd.choice(self.sides) for _ in range(2)]  # лента с выигрышем
        self.win = 14
        self._static()

    # статичные слои
    def _static(self):
        bg = Image.new("RGB", (W, H))
        top, bot = _rgb("#231a56"), _rgb("#0c0d22")
        dr = ImageDraw.Draw(bg)
        for y in range(H):
            k = y / H; dr.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
        self.bg = bg.convert("RGBA")
        self.ray_col = (*_rgb("#7a62ff"), 60)
        glow = Image.new("L", (W, H), 0); ImageDraw.Draw(glow).ellipse([W / 2 - 230, 560 - 230, W / 2 + 230, 560 + 230], fill=170)
        self.glow = glow.filter(ImageFilter.GaussianBlur(80))
        self.f_logo, self.f_title = font("Unbounded-ExtraBold.ttf", 34), font("Unbounded-ExtraBold.ttf", 70)
        self.f_name, self.f_sub = font("Unbounded-ExtraBold.ttf", 42), font("Manrope-Bold.ttf", 30)
        self.f_n1, self.f_n2 = font("Manrope-ExtraBold.ttf", 28), font("Manrope-Bold.ttf", 24)
        self.f_cta, self.f_cta2 = font("Unbounded-ExtraBold.ttf", 33), font("Manrope-ExtraBold.ttf", 28)

    def frame(self, t):
        im = self.bg.copy()
        rays = Image.new("RGBA", (W, H), (0, 0, 0, 0)); rd = ImageDraw.Draw(rays); R = 1600; a0 = math.radians(t * 9)
        for i in range(24):  # лучи рисуются треугольниками - быстрее поворота картинки
            a, b = a0 + math.radians(i * 15), a0 + math.radians(i * 15 + 7)
            rd.polygon([(W / 2, 560), (W / 2 + R * math.cos(a), 560 + R * math.sin(a)), (W / 2 + R * math.cos(b), 560 + R * math.sin(b))], fill=self.ray_col)
        im.alpha_composite(rays)
        pulse = 0.85 + 0.15 * math.sin(t * 3.2)
        im.paste(Image.new("RGBA", (W, H), (*self.c, 255)), (0, 0), self.glow.point(lambda v: int(v * pulse)))
        d = ImageDraw.Draw(im)
        # шапка
        d.text((W / 2, 110), "GiftMafia", font=self.f_logo, fill="#ffc83d", anchor="mm")
        d.text((W / 2 + 3, 196), "Я выиграл!", font=self.f_title, fill=(0, 0, 0, 120), anchor="mm")
        d.text((W / 2, 192), "Я выиграл!", font=self.f_title, fill="white", anchor="mm")
        # рамка ленты
        for y, up in ((300, False), (820, True)):
            d.rounded_rectangle([96, y - 5, W - 96, y + 5], 5, fill="white")
            d.polygon([(W / 2 - 26, y + (-6 if up else 6)), (W / 2 + 26, y + (-6 if up else 6)), (W / 2, y + (-34 if up else 34))], fill="white")
        for x in (176, W - 176): d.rounded_rectangle([x - 3, 352, x + 3, 768], 3, fill=(255, 255, 255, 200))
        # лента: прокрутка с замедлением, потом выигрыш в центре
        spin = min(1, t / 2.4); n = self.win; gap = 330
        pos = _ease_out(spin) * n  # индекс элемента в центре
        for i, it in enumerate(self.strip):
            dx = (i - pos) * gap
            if abs(dx) > W: continue
            center = abs(dx) < gap / 2
            sc = 1.0 if i == n and spin >= 1 else 0.72 + 0.28 * max(0, 1 - abs(dx) / gap)
            if i == n and spin >= 1: sc *= 1 + 0.05 * math.sin((t - 2.4) * 4)
            src = it if (i == n) else it
            w0 = int(src.width * sc * (1 if i == n else 1.25)); h0 = int(src.height * sc * (1 if i == n else 1.25))
            pic = src.resize((max(1, w0), max(1, h0)), Image.BILINEAR)
            if not center or i != n: pic.putalpha(pic.getchannel("A").point(lambda v: int(v * 0.85)))
            im.alpha_composite(pic, (int(W / 2 + dx - pic.width / 2), int(560 - pic.height / 2)))
        d = ImageDraw.Draw(im)
        if spin >= 1:  # искры вокруг выигрыша
            for k, (sx, sy, sr) in enumerate([(230, 400, 22), (500, 440, 16), (470, 720, 20), (250, 690, 14)]):
                a = 0.5 + 0.5 * math.sin(t * 5 + k * 1.7)
                _sparkle(d, sx, sy, sr * (0.6 + 0.6 * a), (255, 236, 160, int(255 * a)))
            a = min(1, (t - 2.4) / 0.4)
            d.text((W / 2, 892), self.gift, font=self.f_name, fill=(255, 255, 255, int(255 * a)), anchor="mm")
            sub = f"{self.model} · {self.value:,}".replace(",", " ")
            tw = d.textlength(sub, font=self.f_sub)
            d.text((W / 2 - 22, 944), sub, font=self.f_sub, fill=(205, 207, 240, int(255 * a)), anchor="mm")
            _star(d, W / 2 - 22 + tw / 2 + 24, 943, 15, (255, 200, 61, int(255 * a)))
        # плашка «Забрать подарок!»
        cy = 1060
        d.rounded_rectangle([84, cy - 48, W - 84, cy + 42], 26, fill="white")
        d.text((W / 2 + 22, cy - 3), "Забрать подарок!", font=self.f_cta, fill="#6c4dff", anchor="mm")
        lx = W / 2 - d.textlength("Забрать подарок!", font=self.f_cta) / 2 - 12
        d.rounded_rectangle([lx - 18, cy - 14, lx + 4, cy + 4], 7, outline="#6c4dff", width=5)
        d.rounded_rectangle([lx - 8, cy - 6, lx + 14, cy + 12], 7, outline="#6c4dff", width=5)
        d.rounded_rectangle([196, cy + 30, W - 196, cy + 92], 22, fill="#6c4dff")
        d.text((W / 2, cy + 61), "ПОПРОБУЙ И ТЫ", font=self.f_cta2, fill="white", anchor="mm")
        # стрелка вниз
        by = 1188 + 8 * math.sin(t * 4)
        d.line([(W / 2 - 30, by - 12), (W / 2, by + 12), (W / 2 + 30, by - 12)], fill=(255, 255, 255, 220), width=7, joint="curve")
        # уведомление сверху
        if t > 2.7:
            k = _back(min(1, (t - 2.7) / 0.5)); y0 = -160 + k * 196
            card = Image.new("RGBA", (W - 40, 120), (0, 0, 0, 0)); cd = ImageDraw.Draw(card)
            cd.rounded_rectangle([0, 0, W - 41, 119], 30, fill=(255, 255, 255, 245))
            cd.ellipse([22, 18, 106, 102], fill="#6c4dff")
            cd.rounded_rectangle([42, 52, 86, 88], 5, fill="white"); cd.rectangle([38, 44, 90, 56], fill="white")
            cd.rectangle([61, 44, 67, 88], fill="#6c4dff")
            cd.ellipse([46, 30, 64, 46], outline="white", width=5); cd.ellipse([64, 30, 82, 46], outline="white", width=5)
            cd.text((128, 44), "GiftMafia", font=self.f_n1, fill="#5a3fd8", anchor="lm")
            cd.text((128, 80), "отправил вам уникальный подарок", font=self.f_n2, fill="#4a4c70", anchor="lm")
            im.alpha_composite(card, (20, int(y0)))
        return im.convert("RGB")

    def video(self, out):
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                              "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                             stdin=subprocess.PIPE)
        for i in range(FPS * SECONDS): p.stdin.write(self.frame(i / FPS).tobytes())
        p.stdin.close()
        if p.wait() != 0: raise RuntimeError("ffmpeg failed")

    def image(self, out):
        self.frame(4.0).save(out, "JPEG", quality=90)
