# main.py -- Asphalt Rush (sprite obstacles + random tint + slightly larger cars)
# Minor spacing tweak: increased vertical gap and per-lane spawn-time gap for easier lane switching.
# Place car_top.png in same folder. Dashboard may pass --car-color.
# Usage:
#   python main.py --lanes 3
#   python main.py --lanes 3 --car-color "#0f766e"
#   Dashboard launches with --caller dashboard

import pygame, random, math, time, sys, os, argparse, json, urllib.request, traceback
from array import array
from collections import defaultdict

# ----------------------------
# CLI args
# ----------------------------
parser = argparse.ArgumentParser(description="Asphalt Rush")
parser.add_argument("--lanes", type=int, default=3, help="number of lanes (2-6)")
parser.add_argument("--hard", action="store_true", help="hard mode (faster)")
parser.add_argument("--caller", type=str, default="", help="caller (optional)")
parser.add_argument("--car-color", type=str, default="", help="hex color for car from dashboard (e.g. #0f766e)")
args = parser.parse_args()

def hex_to_rgb(h):
    if not h: return None
    s = h.lstrip('#')
    if len(s) == 3:
        s = ''.join(c*2 for c in s)
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i+2], 16) for i in (0,2,4))
    except Exception:
        return None

CAR_COLOR_FROM_DASH = hex_to_rgb(args.car_color) if args.car_color else None

# ----------------------------
# Settings
# ----------------------------
WIDTH, HEIGHT = 480, 640
FPS = 60
LANES = max(2, min(6, args.lanes))
LANE_WIDTH = WIDTH // LANES
PLAYER_Y = HEIGHT - 140

# Slightly larger player and obstacles
PLAYER_HEIGHT = 56           # increased from 48
PLAYER_WIDTH_OFFSET = 24     # was 30 previously (so player is wider)
OBSTACLE_HEIGHT = 52         # increased from 44
OBSTACLE_WIDTH_OFFSET = 30   # was 40 previously (so obstacles are wider)

# --- Increased starting spawn interval for a more comfortable pace ---
SPAWN_INTERVAL_START_MS = 1700 if args.hard else 1700
MIN_SPAWN_INTERVAL_MS = 450 if args.hard else 600
SPAWN_DECREASE_MS = 6 if args.hard else 5
OBSTACLE_SPEED_START = 1.9 if args.hard else 1.6
OBSTACLE_SPEED_INCREMENT = 0.008 if args.hard else 0.007

# --- Changed for more room to switch lanes (increased substantially) ---
MIN_VERTICAL_GAP = 600          # was 300 -> big vertical gap (pixels)
MIN_SPAWN_TIME_GAP_MS = 2000    # was 1000 -> per-lane time gap (ms)
# ------------------------------------------------

PAIR_DURATION_SPAWNS = 4
MAX_SIMULTANEOUS_OBSTACLES = 6

K_NEIGHBORS = 3

SAMPLE_RATE = 44100
DEFAULT_ENGINE_FILE = "engine.wav"
DEFAULT_CRASH_FILE = "crash.wav"
DEFAULT_BGM_FILE = "bgm.mp3"

DASHBOARD_SUBMIT_URL = "http://127.0.0.1:5000/submit_score"
DASHBOARD_COLOR_URL = "http://127.0.0.1:5000/api/color"

CAR_SPRITE_FILE = "car_top.png"

# ----------------------------
# TinyKNN
# ----------------------------
class TinyKNN:
    def __init__(self, k=3):
        self.k = k
        self.X = []
        self.y = []
    def add_example(self, features, label):
        self.X.append(features); self.y.append(label)
    def predict(self, features):
        if not self.X: return None
        dists = []
        for xi, yi in zip(self.X, self.y):
            dist = sum((a - b) ** 2 for a, b in zip(xi, features))
            dists.append((math.sqrt(dist), yi))
        dists.sort(key=lambda t: t[0])
        k = min(self.k, len(dists))
        votes = {}
        for i in range(k):
            lbl = dists[i][1]; votes[lbl] = votes.get(lbl, 0) + 1
        best = max(votes.items(), key=lambda x: (x[1], -x[0]))[0]
        return best

# ----------------------------
# audio helpers
# ----------------------------
def make_engine_loop(duration_ms=800, base_freq=78.0):
    n = int(SAMPLE_RATE * duration_ms / 1000.0)
    arr = array('h')
    for i in range(n):
        t = i / SAMPLE_RATE
        base = 0.6 * math.sin(2*math.pi*base_freq*t)
        wob = 0.12 * math.sin(2*math.pi*(base_freq*2.01)*t + 0.7*math.sin(2*math.pi*1.5*t))
        noise = (random.random() - 0.5) * 0.02
        sample = int(32767 * (base + wob + noise))
        arr.append(sample)
    return pygame.mixer.Sound(buffer=arr.tobytes())

def make_crash_sound(duration_ms=700):
    n = int(SAMPLE_RATE * duration_ms / 1000.0)
    arr = array('h')
    for i in range(n):
        t = i / n
        env = math.exp(-5.0 * t)
        thump = 0.6 * math.sin(2*math.pi*120*(i/SAMPLE_RATE)) * math.exp(-8.0*t)
        noise = (random.random()*2 - 1) * 0.6 * env
        sample = int(32767 * max(-1.0, min(1.0, noise + thump)))
        arr.append(sample)
    return pygame.mixer.Sound(buffer=arr.tobytes())

def make_bgm_loop(duration_ms=8000):
    n = int(SAMPLE_RATE * duration_ms / 1000.0)
    arr = array('h')
    for i in range(n):
        t = i / SAMPLE_RATE
        pad = 0.35 * math.sin(2*math.pi*55*t) + 0.22 * math.sin(2*math.pi*82.41*t) + 0.18 * math.sin(2*math.pi*110*t)
        noise = (random.random() - 0.5) * 0.02
        sample = pad + noise
        env = 1.0
        fade_len = int(0.02 * SAMPLE_RATE)
        if i < fade_len: env *= (i / fade_len)
        if i > n - fade_len: env *= ((n - i) / fade_len)
        val = int(32767 * max(-1.0, min(1.0, sample * env)))
        arr.append(val)
    return pygame.mixer.Sound(buffer=arr.tobytes())

def load_or_make_sound(filename, fallback_generator, *args, **kwargs):
    try:
        abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if os.path.exists(abs_path):
            return pygame.mixer.Sound(abs_path)
        else:
            return fallback_generator(*args, **kwargs)
    except Exception:
        return fallback_generator(*args, **kwargs)

# ----------------------------
# Sprite tint helper + caching
# ----------------------------
def tint_sprite(orig_surface, rgb, intensity=1.0):
    if not rgb: return orig_surface.copy()
    try:
        r,g,b = rgb
        surf = orig_surface.copy().convert_alpha()
        w,h = surf.get_size()
        color_surf = pygame.Surface((w,h), flags=pygame.SRCALPHA)
        mul = max(0.18, min(1.0, intensity))
        color_surf.fill((int(r*mul), int(g*mul), int(b*mul), 255))
        surf.blit(color_surf, (0,0), special_flags=pygame.BLEND_RGBA_MULT)
        return surf
    except Exception:
        return orig_surface.copy()

_obstacle_sprite_cache = {}

def get_tinted_obstacle_sprite(base_sprite, rgb, size):
    key = (rgb, size)
    if key in _obstacle_sprite_cache:
        return _obstacle_sprite_cache[key]
    if base_sprite is None:
        return None
    try:
        s = pygame.transform.smoothscale(base_sprite, size)
        tinted = tint_sprite(s, rgb, intensity=1.0)
        _obstacle_sprite_cache[key] = tinted
        return tinted
    except Exception:
        return None

# ----------------------------
# Player & Obstacle (sprite support)
# ----------------------------
class Player:
    def __init__(self, engine_palette=None, sprite_image=None):
        self.width = int((WIDTH // LANES) - PLAYER_WIDTH_OFFSET)
        self.height = PLAYER_HEIGHT
        self.logical_lane = LANES // 2
        self.target_lane = self.logical_lane
        self.current_x = self.logical_lane * (WIDTH // LANES) + ((WIDTH // LANES) - self.width) // 2
        self.target_x = self.current_x
        self.slide_speed = 22.0
        self.sprite_original = sprite_image
        self.sprite = None
        self.color = (30,160,200) if engine_palette is None else engine_palette[0]
        self.strip_color = (255,255,255)
        self.roof_color = (20,20,20)
        self.prepare_sprite()

    @property
    def rect(self):
        return pygame.Rect(int(self.current_x), PLAYER_Y, self.width, self.height)

    def prepare_sprite(self):
        if self.sprite_original:
            try:
                s = pygame.transform.smoothscale(self.sprite_original, (self.width, self.height))
                self.sprite = tint_sprite(s, self.color, intensity=1.0)
            except Exception:
                self.sprite = None
        else:
            self.sprite = None

    def update_color(self, rgb):
        if rgb:
            self.color = rgb
            if self.sprite_original:
                try:
                    s = pygame.transform.smoothscale(self.sprite_original, (self.width, self.height))
                    self.sprite = tint_sprite(s, self.color, intensity=1.0)
                except Exception:
                    pass

    def request_lane_change(self, delta):
        if abs(self.target_x - self.current_x) > 2.0:
            return
        new_lane = max(0, min(LANES - 1, self.logical_lane + delta))
        if new_lane == self.logical_lane:
            return
        self.target_lane = new_lane
        self.target_x = new_lane * (WIDTH // LANES) + ((WIDTH // LANES) - self.width) // 2

    def update(self):
        dx = self.target_x - self.current_x
        if abs(dx) < 0.5:
            self.current_x = self.target_x
            self.logical_lane = self.target_lane
        else:
            step = math.copysign(min(abs(dx), self.slide_speed * (1.0 + (abs(dx)/100.0))), dx)
            self.current_x += step

    def draw(self, surface):
        r = self.rect
        if self.sprite:
            shadow = pygame.Surface((r.width-6, 8), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (6,6,6,180), shadow.get_rect())
            surface.blit(shadow, (r.x+6, r.y + r.height - 6))
            surface.blit(self.sprite, (r.x, r.y))
        else:
            shadow_surf = pygame.Surface((self.width-10, 8), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow_surf, (6,6,6,160), shadow_surf.get_rect())
            surface.blit(shadow_surf, (r.x+6, r.y + r.height - 6))
            body = pygame.Rect(r.x, r.y + 6, r.width, r.height - 6)
            pygame.draw.rect(surface, (4,4,4), body, border_radius=12)
            pygame.draw.rect(surface, self.color, body.inflate(-2, -2), border_radius=12)

class Obstacle:
    DEFAULT_COLORS = [(200,30,30),(30,120,200),(40,200,120),(200,140,30),(160,30,200),(100,100,100)]
    def __init__(self, lane, y, speed, base_sprite=None):
        self.lane = lane
        self.width = int((WIDTH // LANES) - OBSTACLE_WIDTH_OFFSET)
        self.height = OBSTACLE_HEIGHT
        self.x = lane * (WIDTH // LANES) + ((WIDTH // LANES) - self.width) // 2
        self.y = y
        self.speed = speed
        self.color = random.choice(Obstacle.DEFAULT_COLORS)
        self.strip_color = (min(255,self.color[0]+30), min(255,self.color[1]+30), min(255,self.color[2]+30))
        self.base_sprite = base_sprite
        self.tinted_sprite = None
        if self.base_sprite:
            size = (self.width, self.height)
            try:
                self.tinted_sprite = get_tinted_obstacle_sprite(self.base_sprite, self.color, size)
            except Exception:
                self.tinted_sprite = None

    @property
    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.width, self.height)

    def update(self):
        self.y += self.speed

    def draw(self, surface):
        r = self.rect
        if self.tinted_sprite:
            shadow = pygame.Surface((r.width-6, 10), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (6,6,6,170), shadow.get_rect())
            surface.blit(shadow, (r.x+6, r.y + r.height - 6))
            surface.blit(self.tinted_sprite, (r.x, r.y))
            return
        shadow_surf = pygame.Surface((r.width-10, 8), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (10,10,10,160), shadow_surf.get_rect())
        surface.blit(shadow_surf, (r.x+6, r.y + r.height - 6))
        body = pygame.Rect(r.x, r.y + 6, r.width, r.height - 6)
        pygame.draw.rect(surface, (6,6,6), body, border_radius=10)
        pygame.draw.rect(surface, self.color, body.inflate(-2,-2), border_radius=10)
        roof_w = r.width // 2
        roof_rect = pygame.Rect(r.x + (r.width - roof_w)//2, r.y - 2, roof_w, 18)
        pygame.draw.rect(surface, (15,15,20), roof_rect, border_radius=6)
        window = roof_rect.inflate(-6,-6)
        pygame.draw.rect(surface, (140,180,220), window, border_radius=4)
        strip = pygame.Rect(r.x + r.width//3, r.y + r.height//3, r.width//3, 6)
        pygame.draw.rect(surface, self.strip_color, strip, border_radius=3)
        wheel_radius = 6
        pygame.draw.circle(surface, (20,20,20), (r.x + 12, r.y + r.height - 6), wheel_radius)
        pygame.draw.circle(surface, (20,20,20), (r.x + r.width - 12, r.y + r.height - 6), wheel_radius)

# ----------------------------
# Road + lane numbers
# ----------------------------
lane_dash_offset = 0.0
def draw_road(surface, obstacle_speed, dt_ms):
    global lane_dash_offset
    edge = 20
    surface.fill((24,24,26))
    road_x = edge; road_w = WIDTH - 2*edge
    pygame.draw.rect(surface, (8,8,10), (road_x, 0, road_w, HEIGHT))
    dash_h = 18; gap = 14; lane_w = WIDTH // LANES
    lane_dash_offset += (obstacle_speed * (dt_ms / 16.0)) * 2.0
    total_step = dash_h + gap
    lane_dash_offset %= total_step
    for i in range(1, LANES):
        x = road_x + i * lane_w
        y = -total_step + (lane_dash_offset % total_step)
        while y < HEIGHT + total_step:
            pygame.draw.line(surface, (245,245,245), (x, y), (x, y+dash_h), 4)
            y += total_step
    pygame.draw.rect(surface, (6,6,8), (0,0,edge,HEIGHT))
    pygame.draw.rect(surface, (6,6,8), (WIDTH-edge,0,edge,HEIGHT))
    font = pygame.font.SysFont(None, 20)
    for i in range(LANES):
        cx = road_x + i * lane_w + lane_w//2
        txt = font.render(str(i+1), True, (245,245,245))
        surface.blit(txt, (cx - txt.get_width()//2, 8))

# ----------------------------
# Networking: submit score & fetch color
# ----------------------------
def submit_score_to_dashboard(score, lanes):
    data = json.dumps({"score": int(score), "lanes": int(lanes)}).encode("utf-8")
    req = urllib.request.Request(DASHBOARD_SUBMIT_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=0.9)
    except Exception:
        pass

def fetch_dashboard_color():
    try:
        req = urllib.request.Request(DASHBOARD_COLOR_URL, headers={"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            raw = resp.read(); data = json.loads(raw.decode("utf-8")); return data.get("hex")
    except Exception:
        return None

# ----------------------------
# Focus helper (Windows)
# ----------------------------
def bring_window_to_front(win_caption=None):
    try:
        if os.name != "nt": return
        import ctypes, time as _t
        user32 = ctypes.windll.user32
        if win_caption:
            hwnd = user32.FindWindowW(None, win_caption)
        else:
            hwnd = user32.FindWindowW(None, pygame.display.get_caption()[0] if pygame.display.get_caption()[0] else None)
        if hwnd:
            SWP_NOSIZE = 0x0001; SWP_NOMOVE = 0x0002
            HWND_TOPMOST = -1; HWND_NOTOPMOST = -2
            user32.SetForegroundWindow(hwnd)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0,0,0,0, SWP_NOMOVE | SWP_NOSIZE)
            _t.sleep(0.05)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0,0,0,0, SWP_NOMOVE | SWP_NOSIZE)
    except Exception:
        pass

# ----------------------------
# Main loop
# ----------------------------
def load_sprite_if_available():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CAR_SPRITE_FILE)
    if os.path.exists(path):
        try:
            img = pygame.image.load(path).convert_alpha()
            print("[main] sprite loaded:", path)
            return img
        except Exception as e:
            print("[main] failed loading sprite:", e)
            return None
    else:
        print("[main] sprite not found at:", path)
    return None

def main():
    try:
        pygame.init()
        try:
            pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
        except Exception:
            pass
        try:
            pygame.mixer.init()
        except Exception:
            pass

        screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption(f"Asphalt Rush — {LANES} lanes")
        if args.caller == "dashboard":
            bring_window_to_front(pygame.display.get_caption()[0])

        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 26)
        big_font = pygame.font.SysFont(None, 48)

        engine_sound = load_or_make_sound(DEFAULT_ENGINE_FILE, make_engine_loop, duration_ms=900, base_freq=78.0)
        crash_sound = load_or_make_sound(DEFAULT_CRASH_FILE, make_crash_sound, duration_ms=700)
        bgm_sound = load_or_make_sound(DEFAULT_BGM_FILE, make_bgm_loop, duration_ms=8000)
        bgm_channel = None; bgm_volume = 0.80; bgm_muted = False

        try:
            bgm_channel = bgm_sound.play(-1)
            if bgm_channel:
                bgm_channel.set_volume(bgm_volume)
        except Exception:
            bgm_channel = None

        engine_channel = None
        try:
            engine_channel = engine_sound.play(-1)
            if engine_channel:
                engine_channel.set_volume(0.45)
        except Exception:
            engine_channel = None

        base_sprite = load_sprite_if_available()

        global LANE_WIDTH
        LANE_WIDTH = WIDTH // LANES

        default_color_rgb = (15,119,110)
        init_rgb = CAR_COLOR_FROM_DASH if CAR_COLOR_FROM_DASH else default_color_rgb

        player = Player(engine_palette=[init_rgb], sprite_image=base_sprite)
        player.update_color(init_rgb)

        obstacles = []
        score = 0
        obstacle_speed = OBSTACLE_SPEED_START
        spawn_interval = SPAWN_INTERVAL_START_MS
        last_spawn_time = pygame.time.get_ticks()

        knn = TinyKNN(k=K_NEIGHBORS)
        last_obstacle_spawn_time = None
        last_obstacle_lane = None
        memory_limit = 900
        total_predictions = 0
        correct_predictions = 0
        last_prediction_label = None
        current_pair = None
        pair_spawns_left = 0
        last_lane_spawned_in_pair = None
        lane_last_spawn_time = {i: -99999 for i in range(LANES)}
        running = True
        playing = True
        total_spawned = 0
        lane_recent = None

        poll_enabled = (args.caller == "dashboard")
        color_poll_interval = 0.9
        last_color_poll = time.time()

        print("[main] game loop starting. poll_enabled:", poll_enabled, "initial_color:", init_rgb)

        try:
            pygame.event.set_allowed(None)
            pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP, pygame.MOUSEBUTTONDOWN])
        except Exception:
            pass

        while running:
            dt = clock.tick(FPS)
            now = pygame.time.get_ticks()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    print("[main] QUIT event")
                    running = False
                elif event.type == pygame.KEYDOWN:
                    try:
                        print(f"[main] KEYDOWN: key={event.key}")
                    except Exception:
                        pass
                    if event.key == pygame.K_m:
                        bgm_muted = not bgm_muted
                        try:
                            if bgm_channel:
                                bgm_channel.set_volume(0.0 if bgm_muted else bgm_volume)
                        except Exception:
                            pass
                    elif event.key in (pygame.K_PLUS, pygame.K_EQUALS) or event.key == pygame.K_KP_PLUS:
                        bgm_volume = min(1.0, bgm_volume + 0.1)
                        if not bgm_muted and bgm_channel:
                            bgm_channel.set_volume(bgm_volume)
                    elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                        bgm_volume = max(0.0, bgm_volume - 0.1)
                        if not bgm_muted and bgm_channel:
                            bgm_channel.set_volume(bgm_volume)

                    if event.key in (pygame.K_LEFT, pygame.K_a):
                        player.request_lane_change(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_d):
                        player.request_lane_change(1)
                    elif event.key == pygame.K_r:
                        print("[main] Restart requested (R)")
                        return main()
                    elif event.key == pygame.K_q:
                        print("[main] Quit requested (Q)")
                        running = False

            if poll_enabled and (time.time() - last_color_poll) >= color_poll_interval:
                last_color_poll = time.time()
                try:
                    hexv = fetch_dashboard_color()
                    if hexv:
                        rgb = hex_to_rgb(hexv)
                        if rgb and rgb != player.color:
                            print("[main] dashboard color poll -> updating player color:", hexv, rgb)
                            player.update_color(rgb)
                except Exception:
                    traceback.print_exc()

            if not playing:
                pygame.display.flip()
                continue

            if pair_spawns_left <= 0 or current_pair is None:
                pairs = [(i,i+1) for i in range(LANES-1)]
                current_pair = random.choice(pairs)
                pair_spawns_left = PAIR_DURATION_SPAWNS
                last_lane_spawned_in_pair = None

            # spawn
            if now - last_spawn_time >= spawn_interval:
                if len(obstacles) < MAX_SIMULTANEOUS_OBSTACLES:
                    candidate_lanes = []
                    for lane in current_pair:
                        # blocked_by_vert uses the increased MIN_VERTICAL_GAP
                        blocked_by_vert = any((ob.lane == lane and ob.y < MIN_VERTICAL_GAP) for ob in obstacles)
                        time_ok = (now - lane_last_spawn_time.get(lane, -99999)) >= MIN_SPAWN_TIME_GAP_MS
                        if (not blocked_by_vert) and time_ok:
                            candidate_lanes.append(lane)
                    if candidate_lanes:
                        if last_lane_spawned_in_pair in candidate_lanes:
                            others = [l for l in candidate_lanes if l != last_lane_spawned_in_pair]
                            choose_lane = others[0] if others else random.choice(candidate_lanes)
                        else:
                            choose_lane = random.choice(candidate_lanes)

                        prediction_label = None
                        if last_obstacle_spawn_time is not None and last_obstacle_lane is not None:
                            time_gap_ms = now - last_obstacle_spawn_time
                            feat = [last_obstacle_lane / max(1,(LANES-1)), min(time_gap_ms,2000)/2000.0, min(obstacle_speed,10)/10.0]
                            pred = knn.predict(feat)
                            if pred in candidate_lanes and random.random() < 0.45:
                                choose_lane = pred
                            prediction_label = pred

                        # spawn higher so player has more time: start y negative larger
                        ob = Obstacle(choose_lane, -160, obstacle_speed, base_sprite)
                        obstacles.append(ob)
                        lane_last_spawn_time[choose_lane] = now
                        last_lane_spawned_in_pair = choose_lane
                        lane_recent = choose_lane
                        total_spawned += 1

                        if last_obstacle_spawn_time is not None and last_obstacle_lane is not None:
                            time_gap_ms = now - last_obstacle_spawn_time
                            feat_train = [last_obstacle_lane / max(1,(LANES-1)), min(time_gap_ms,2000)/2000.0, min(obstacle_speed,10)/10.0]
                            knn.add_example(feat_train, choose_lane)
                            if len(knn.X) > memory_limit:
                                knn.X.pop(0); knn.y.pop(0)

                        if prediction_label is not None:
                            total_predictions += 1
                            if prediction_label == choose_lane:
                                correct_predictions += 1
                            last_prediction_label = prediction_label

                        last_obstacle_spawn_time = now
                        last_obstacle_lane = choose_lane

                        pair_spawns_left -= 1

                        if spawn_interval > MIN_SPAWN_INTERVAL_MS:
                            spawn_interval = max(MIN_SPAWN_INTERVAL_MS, spawn_interval - SPAWN_DECREASE_MS)
                        obstacle_speed += OBSTACLE_SPEED_INCREMENT

                last_spawn_time = now

            # updates
            for ob in list(obstacles):
                ob.update()
                if ob.y > HEIGHT + 80:
                    obstacles.remove(ob)
                    score += 1

            player.update()

            collided = any(player.rect.colliderect(ob.rect) for ob in obstacles)
            if collided:
                try:
                    if engine_channel:
                        engine_channel.fadeout(300)
                except Exception:
                    pass
                try:
                    crash_sound.play()
                except Exception:
                    pass
                try:
                    if bgm_channel and not bgm_muted:
                        bgm_channel.fadeout(800)
                except Exception:
                    pass

                playing = False
                game_over(screen, score, font, big_font)
                submit_score_to_dashboard(score, LANES)

                # reinit
                player = Player(engine_palette=[player.color], sprite_image=player.sprite_original)
                player.update_color(player.color)
                obstacles = []
                score = 0
                obstacle_speed = OBSTACLE_SPEED_START
                spawn_interval = SPAWN_INTERVAL_START_MS
                last_spawn_time = pygame.time.get_ticks()
                knn = TinyKNN(k=K_NEIGHBORS)
                last_obstacle_spawn_time = None
                last_obstacle_lane = None
                total_predictions = correct_predictions = 0
                last_prediction_label = None
                current_pair = None
                pair_spawns_left = 0
                last_lane_spawned_in_pair = None
                lane_last_spawn_time = {i: -99999 for i in range(LANES)}
                total_spawned = 0
                lane_recent = None

                try:
                    bgm_channel = bgm_sound.play(-1)
                    if bgm_channel and not bgm_muted:
                        bgm_channel.set_volume(bgm_volume)
                except Exception:
                    bgm_channel = None
                try:
                    engine_channel = engine_sound.play(-1)
                    if engine_channel:
                        engine_channel.set_volume(0.45)
                except Exception:
                    engine_channel = None

                playing = True
                continue

            # draw
            draw_road(screen, obstacle_speed, dt)
            for ob in obstacles:
                ob.draw(screen)
            player.draw(screen)

            ai_text = "AI: N/A"
            if last_prediction_label is not None and total_predictions > 0:
                acc = (correct_predictions / total_predictions) * 100 if total_predictions > 0 else 0.0
                ai_text = f"AI predicted last: Lane {last_prediction_label+1} | Acc: {acc:.1f}%"

            score_surf = font.render(f"Score: {score}", True, (220,220,220))
            screen.blit(score_surf, (WIDTH - 140, 12))
            ai_surf = font.render(ai_text, True, (220,220,220))
            screen.blit(ai_surf, (12, 12))
            hint = font.render("Left/Right or A/D — R restart, Q quit | M mute", True, (200,200,200))
            screen.blit(hint, (12, HEIGHT - 28))

            pygame.display.flip()

        pygame.quit()
    except KeyboardInterrupt:
        pygame.quit()
        print("\nExited by user (KeyboardInterrupt).")
        sys.exit(0)
    except Exception:
        print("[main] Unexpected error:", traceback.format_exc())
        pygame.quit()
        sys.exit(1)

def game_over(surface, score, font, big_font):
    clock = pygame.time.Clock()
    overlay = pygame.Surface((WIDTH, HEIGHT))
    overlay.set_alpha(220)
    overlay.fill((12,12,14))
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_r:
                    return
                if ev.key == pygame.K_q:
                    pygame.quit(); sys.exit(0)
        surface.blit(overlay, (0,0))
        go_surf = big_font.render("GAME OVER", True, (220,80,80))
        surface.blit(go_surf, ((WIDTH - go_surf.get_width())//2, HEIGHT//3))
        info = font.render(f"Final score: {score}  — Press R to Restart or Q to Quit", True, (220,220,220))
        surface.blit(info, ((WIDTH - info.get_width())//2, HEIGHT//2 + 40))
        pygame.display.flip()
        clock.tick(30)

if __name__ == "__main__":
    print(f"[main] Starting Asphalt Rush — lanes={LANES}, hard={args.hard}, caller={args.caller}, car_color={args.car_color}")
    main()