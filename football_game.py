import pygame
import serial
import serial.tools.list_ports
import threading
import time
import re
import os
import math
import random


# ============================================================
# SETTINGS
# ============================================================

WIDTH = 1000
HEIGHT = 700
FPS = 60

BAUD_RATE = 115200

BALL_START_X = WIDTH // 2
BALL_START_Y = 610

GOAL_LEFT = 230
GOAL_RIGHT = 770
GOAL_TOP = 145
GOAL_BOTTOM = 325

KEEPER_MIN_X = 300
KEEPER_MAX_X = 700

KEEPER_SPEED = 155


# ============================================================
# PYGAME
# ============================================================

pygame.mixer.pre_init(
    frequency=44100,
    size=-16,
    channels=2,
    buffer=1024
)

pygame.init()
screen = pygame.display.set_mode(
    (WIDTH, HEIGHT)
)

pygame.display.set_caption(
    "ESP32 Motion Football"
)

clock = pygame.time.Clock()

# ============================================================
# GOALKEEPER IMAGE
# ============================================================

keeper_image = pygame.image.load(
    "images/goalkeeper.png"
).convert_alpha()

keeper_image = pygame.transform.smoothscale(
    keeper_image,
    (150, 180)
)
# ============================================================
# FONTS
# ============================================================

font_small = pygame.font.SysFont(
    "arial",
    18
)

font_medium = pygame.font.SysFont(
    "arial",
    25,
    bold=True
)

font_large = pygame.font.SysFont(
    "arial",
    42,
    bold=True
)

font_huge = pygame.font.SysFont(
    "arial",
    68,
    bold=True
)


# ============================================================
# SOUNDS
# ============================================================

goal_sound = None
miss_sound = None

try:
    goal_sound = pygame.mixer.Sound(
        "sounds/goal.mp3"
    )

    print("Goal sound loaded")

except Exception as e:
    print("Goal sound error:", e)


try:
    miss_sound = pygame.mixer.Sound(
        "sounds/miss.mp3"
    )

    print("Miss sound loaded")

except Exception as e:
    print("Miss sound error:", e)


# ============================================================
# ESP32 DATA
# ============================================================

latest_aim = 0
latest_kick = None

serial_connected = False

serial_lock = threading.Lock()


# ============================================================
# FIND ESP32
# ============================================================

def find_esp32():

    ports = serial.tools.list_ports.comports()

    for port in ports:

        if (
            "ttyUSB" in port.device
            or
            "ttyACM" in port.device
        ):
            return port.device

    return None


# ============================================================
# SERIAL THREAD
# ============================================================

def serial_thread():

    global latest_aim
    global latest_kick
    global serial_connected

    while True:

        port = find_esp32()

        if port is None:

            serial_connected = False
            time.sleep(1)
            continue

        try:

            ser = serial.Serial(
                port,
                BAUD_RATE,
                timeout=1
            )

            time.sleep(1)

            serial_connected = True

            print(
                "ESP32 connected:",
                port
            )

            while True:

                raw = ser.readline()

                if not raw:
                    continue

                try:

                    line = (
                        raw.decode(
                            "utf-8",
                            errors="ignore"
                        )
                        .strip()
                    )

                except Exception:
                    continue


                # ------------------------------
                # AIM
                # ------------------------------

                aim_match = re.match(
                    r"^AIM:(-?\d+)$",
                    line
                )

                if aim_match:

                    value = int(
                        aim_match.group(1)
                    )

                    value = max(
                        -100,
                        min(100, value)
                    )

                    with serial_lock:
                        latest_aim = value

                    continue


                # ------------------------------
                # KICK
                # ------------------------------

                kick_match = re.match(
                    r"^KICK:(\d+)$",
                    line
                )

                if kick_match:

                    power = int(
                        kick_match.group(1)
                    )

                    power = max(
                        1,
                        min(100, power)
                    )

                    with serial_lock:
                        latest_kick = power

                    print(
                        "SHOT POWER:",
                        power
                    )

                    continue


                # ------------------------------
                # DIAGNOSTIC
                # ------------------------------

                if line.startswith(
                    "SHOT_DATA:"
                ):
                    print(line)


        except Exception as e:

            serial_connected = False

            print(
                "Serial disconnected:",
                e
            )

            time.sleep(1)


threading.Thread(
    target=serial_thread,
    daemon=True
).start()


# ============================================================
# GAME STATE
# ============================================================

STATE_READY = 0
STATE_SHOOTING = 1
STATE_RESULT = 2

game_state = STATE_READY

goals = 0
shots = 0
streak = 0

display_aim = 0.0

shot_aim = 0
shot_power = 0

ball_x = float(BALL_START_X)
ball_y = float(BALL_START_Y)
ball_radius = 29

shot_start_time = 0

result_text = ""
result_timer = 0


# ============================================================
# GOALKEEPER
# ============================================================

keeper_x = WIDTH / 2
keeper_direction = 1


# ============================================================
# DRAW STADIUM
# ============================================================

def draw_stadium():

    # Background / crowd
    pygame.draw.rect(
        screen,
        (29, 37, 48),
        (0, 0, WIDTH, 125)
    )

    # Crowd rows
    for row_y in range(72, 118, 14):

        offset = (
            0 if
            (row_y // 14) % 2 == 0
            else 8
        )

        for x in range(
            12 + offset,
            WIDTH,
            22
        ):

            colors = [
                (230, 230, 230),
                (70, 130, 200),
                (210, 70, 70),
                (235, 190, 60),
                (100, 180, 100)
            ]

            pygame.draw.circle(
                screen,
                random.choice(colors),
                (x, row_y),
                3
            )


    # Barrier
    pygame.draw.rect(
        screen,
        (205, 210, 215),
        (0, 120, WIDTH, 8)
    )


# ============================================================
# DRAW PITCH
# ============================================================

def draw_pitch():

    pitch_top = 128

    pygame.draw.rect(
        screen,
        (45, 137, 64),
        (
            0,
            pitch_top,
            WIDTH,
            HEIGHT - pitch_top
        )
    )


    # Grass stripes
    stripe_width = 100

    for i in range(10):

        if i % 2 == 0:

            pygame.draw.rect(
                screen,
                (50, 148, 69),
                (
                    i * stripe_width,
                    pitch_top,
                    stripe_width,
                    HEIGHT - pitch_top
                )
            )


    # Penalty area
    pygame.draw.rect(
        screen,
        (240, 240, 240),
        (
            155,
            128,
            690,
            300
        ),
        4
    )


    # Small goal area
    pygame.draw.rect(
        screen,
        (240, 240, 240),
        (
            300,
            128,
            400,
            145
        ),
        4
    )


    # Penalty spot
    pygame.draw.circle(
        screen,
        (245, 245, 245),
        (
            WIDTH // 2,
            475
        ),
        5
    )


    # Penalty arc
    pygame.draw.arc(
        screen,
        (240, 240, 240),
        (
            395,
            405,
            210,
            130
        ),
        math.radians(20),
        math.radians(160),
        4
    )


# ============================================================
# DRAW GOAL
# ============================================================

def draw_goal():

    goal_width = (
        GOAL_RIGHT -
        GOAL_LEFT
    )

    goal_height = (
        GOAL_BOTTOM -
        GOAL_TOP
    )


    # Goal shadow
    pygame.draw.rect(
        screen,
        (30, 80, 38),
        (
            GOAL_LEFT + 10,
            GOAL_TOP + 12,
            goal_width,
            goal_height
        ),
        0
    )


    # Net vertical lines
    for x in range(
        GOAL_LEFT,
        GOAL_RIGHT + 1,
        30
    ):

        pygame.draw.line(
            screen,
            (205, 215, 210),
            (
                x,
                GOAL_TOP
            ),
            (
                x,
                GOAL_BOTTOM
            ),
            1
        )


    # Net horizontal lines
    for y in range(
        GOAL_TOP,
        GOAL_BOTTOM + 1,
        24
    ):

        pygame.draw.line(
            screen,
            (205, 215, 210),
            (
                GOAL_LEFT,
                y
            ),
            (
                GOAL_RIGHT,
                y
            ),
            1
        )


    # Goal frame
    pygame.draw.line(
        screen,
        (250, 250, 250),
        (
            GOAL_LEFT,
            GOAL_BOTTOM
        ),
        (
            GOAL_LEFT,
            GOAL_TOP
        ),
        8
    )

    pygame.draw.line(
        screen,
        (250, 250, 250),
        (
            GOAL_RIGHT,
            GOAL_BOTTOM
        ),
        (
            GOAL_RIGHT,
            GOAL_TOP
        ),
        8
    )

    pygame.draw.line(
        screen,
        (250, 250, 250),
        (
            GOAL_LEFT,
            GOAL_TOP
        ),
        (
            GOAL_RIGHT,
            GOAL_TOP
        ),
        8
    )


# ============================================================
# DRAW GOALKEEPER
# ============================================================
def draw_keeper(x):

    rect = keeper_image.get_rect(
        midbottom=(
            int(x),
            345
        )
    )

    screen.blit(
        keeper_image,
        rect
    )
# DRAW FOOTBALL
# ============================================================

def draw_football(x, y, radius):

    x = int(x)
    y = int(y)
    radius = int(radius)

    if radius < 5:
        radius = 5


    # Shadow
    pygame.draw.ellipse(
        screen,
        (35, 105, 45),
        (
            x - radius,
            y + radius - 3,
            radius * 2,
            max(6, radius // 2)
        )
    )


    # Ball
    pygame.draw.circle(
        screen,
        (247, 247, 242),
        (
            x,
            y
        ),
        radius
    )

    pygame.draw.circle(
        screen,
        (30, 30, 32),
        (
            x,
            y
        ),
        radius,
        2
    )


    # Center pentagon
    points = []

    center_size = radius * 0.36

    for i in range(5):

        angle = (
            -math.pi / 2
            +
            i * 2 * math.pi / 5
        )

        points.append(
            (
                x +
                math.cos(angle)
                * center_size,

                y +
                math.sin(angle)
                * center_size
            )
        )


    pygame.draw.polygon(
        screen,
        (35, 35, 38),
        points
    )


    # Outer panels
    for angle in [
        0,
        72,
        144,
        216,
        288
    ]:

        rad = math.radians(angle)

        px = (
            x +
            math.cos(rad)
            * radius * 0.70
        )

        py = (
            y +
            math.sin(rad)
            * radius * 0.70
        )

        pygame.draw.circle(
            screen,
            (40, 40, 42),
            (
                int(px),
                int(py)
            ),
            max(
                3,
                radius // 7
            )
        )


# ============================================================
# AIM TARGET
# ============================================================

def get_target_x(aim):

    normalized = (
        aim + 100
    ) / 200.0

    return (
        GOAL_LEFT + 45
        +
        normalized
        *
        (
            GOAL_RIGHT -
            GOAL_LEFT -
            90
        )
    )


# ============================================================
# DRAW DOTTED AIM
# ============================================================

def draw_aim_line():

    target_x = get_target_x(
        display_aim
    )

    target_y = 225


    start_x = BALL_START_X
    start_y = BALL_START_Y - 40


    dx = (
        target_x -
        start_x
    )

    dy = (
        target_y -
        start_y
    )


    distance = math.sqrt(
        dx * dx +
        dy * dy
    )


    if distance == 0:
        return


    spacing = 25

    steps = int(
        distance /
        spacing
    )


    for i in range(
        1,
        steps
    ):

        t = i / steps

        x = (
            start_x +
            dx * t
        )

        y = (
            start_y +
            dy * t
        )

        pygame.draw.circle(
            screen,
            (250, 225, 70),
            (
                int(x),
                int(y)
            ),
            4
        )


    # Target
    pygame.draw.circle(
        screen,
        (250, 225, 70),
        (
            int(target_x),
            target_y
        ),
        16,
        3
    )

    pygame.draw.circle(
        screen,
        (250, 225, 70),
        (
            int(target_x),
            target_y
        ),
        4
    )


# ============================================================
# HUD
# ============================================================

def draw_hud():

    # --------------------------------------------------------
    # TOP HUD
    # --------------------------------------------------------

    pygame.draw.rect(
        screen,
        (20, 25, 32),
        (
            0,
            0,
            WIDTH,
            65
        )
    )


    # Goals
    goals_label = font_small.render(
        "GOALS",
        True,
        (175, 185, 195)
    )

    goals_value = font_medium.render(
        str(goals),
        True,
        (255, 255, 255)
    )

    screen.blit(
        goals_label,
        (35, 10)
    )

    screen.blit(
        goals_value,
        (35, 31)
    )


    # Shots
    shots_label = font_small.render(
        "SHOTS",
        True,
        (175, 185, 195)
    )

    shots_value = font_medium.render(
        str(shots),
        True,
        (255, 255, 255)
    )

    screen.blit(
        shots_label,
        (145, 10)
    )

    screen.blit(
        shots_value,
        (145, 31)
    )


    # Streak
    streak_label = font_small.render(
        "STREAK",
        True,
        (175, 185, 195)
    )

    streak_value = font_medium.render(
        str(streak),
        True,
        (255, 255, 255)
    )

    screen.blit(
        streak_label,
        (255, 10)
    )

    screen.blit(
        streak_value,
        (255, 31)
    )


    # Title
    title = font_medium.render(
        "MOTION FOOTBALL",
        True,
        (255, 255, 255)
    )

    title_rect = title.get_rect(
        center=(
            WIDTH // 2,
            33
        )
    )

    screen.blit(
        title,
        title_rect
    )


    # Connection status
    if serial_connected:

        status_text = (
            "ESP32 CONNECTED"
        )

        status_color = (
            90,
            225,
            125
        )

    else:

        status_text = (
            "WAITING FOR ESP32"
        )

        status_color = (
            245,
            100,
            100
        )


    status = font_small.render(
        status_text,
        True,
        status_color
    )

    status_rect = status.get_rect(
        right=WIDTH - 30,
        centery=33
    )

    screen.blit(
        status,
        status_rect
    )


    # Status dot
    pygame.draw.circle(
        screen,
        status_color,
        (
            status_rect.left - 13,
            33
        ),
        5
    )


    # --------------------------------------------------------
    # AIM CARD - BOTTOM LEFT
    # --------------------------------------------------------

    pygame.draw.rect(
        screen,
        (20, 25, 32),
        (
            25,
            590,
            180,
            82
        ),
        border_radius=12
    )


    aim_label = font_small.render(
        "HAND AIM",
        True,
        (175, 185, 195)
    )

    screen.blit(
        aim_label,
        (
            42,
            601
        )
    )


    if display_aim < -8:

        direction = "LEFT"

    elif display_aim > 8:

        direction = "RIGHT"

    else:

        direction = "CENTER"


    aim_text = font_medium.render(
        direction,
        True,
        (250, 225, 70)
    )

    screen.blit(
        aim_text,
        (
            42,
            626
        )
    )


    # --------------------------------------------------------
    # POWER CARD - BOTTOM RIGHT
    # --------------------------------------------------------

    pygame.draw.rect(
        screen,
        (20, 25, 32),
        (
            795,
            590,
            180,
            82
        ),
        border_radius=12
    )


    power_label = font_small.render(
        "LAST SHOT",
        True,
        (175, 185, 195)
    )

    screen.blit(
        power_label,
        (
            812,
            601
        )
    )


    power_text = font_medium.render(
        f"{shot_power} / 100",
        True,
        (255, 255, 255)
    )

    screen.blit(
        power_text,
        (
            812,
            626
        )
    )


# ============================================================
# INSTRUCTION
# ============================================================

def draw_instruction():

    if game_state != STATE_READY:
        return


    text = font_small.render(
        "TILT YOUR HAND TO AIM   •   SWING TO SHOOT",
        True,
        (255, 255, 255)
    )


    rect = text.get_rect(
        center=(
            WIDTH // 2,
            665
        )
    )


    pygame.draw.rect(
        screen,
        (20, 25, 32),
        (
            rect.left - 18,
            rect.top - 8,
            rect.width + 36,
            rect.height + 16
        ),
        border_radius=10
    )


    screen.blit(
        text,
        rect
    )


# ============================================================
# RESULT MESSAGE
# ============================================================

def draw_result():

    if game_state != STATE_RESULT:
        return


    if result_text == "GOAL!":

        color = (
            255,
            225,
            65
        )

    else:

        color = (
            255,
            255,
            255
        )


    shadow = font_huge.render(
        result_text,
        True,
        (25, 25, 25)
    )

    text = font_huge.render(
        result_text,
        True,
        color
    )


    rect = text.get_rect(
        center=(
            WIDTH // 2,
            420
        )
    )


    screen.blit(
        shadow,
        (
            rect.x + 4,
            rect.y + 4
        )
    )

    screen.blit(
        text,
        rect
    )


# ============================================================
# RESET BALL
# ============================================================

def reset_ball():

    global ball_x
    global ball_y
    global ball_radius
    global game_state

    ball_x = float(
        BALL_START_X
    )

    ball_y = float(
        BALL_START_Y
    )

    ball_radius = 29

    game_state = STATE_READY


# ============================================================
# START SHOT
# ============================================================

def start_shot(power):

    global game_state
    global shot_power
    global shot_aim
    global shot_start_time
    global shots

    if game_state != STATE_READY:
        return


    shot_power = power

    # Freeze the displayed aim
    shot_aim = int(
        display_aim
    )

    shots += 1

    shot_start_time = (
        pygame.time.get_ticks()
    )

    game_state = STATE_SHOOTING


# ============================================================
# UPDATE SHOT
# ============================================================

def update_shot():

    global ball_x
    global ball_y
    global ball_radius

    global game_state

    global goals
    global streak

    global result_text
    global result_timer


    elapsed = (
        pygame.time.get_ticks()
        -
        shot_start_time
    )


    # Shot duration changes slightly with power
    duration = (
        820
        -
        shot_power * 2.8
    )

    duration = max(
        470,
        duration
    )


    progress = (
        elapsed /
        duration
    )


    if progress > 1:
        progress = 1


    target_x = get_target_x(
        shot_aim
    )


    # Smooth acceleration toward goal
    eased = (
        progress * progress
        *
        (
            3 -
            2 * progress
        )
    )


    ball_x = (
        BALL_START_X
        +
        (
            target_x -
            BALL_START_X
        )
        * eased
    )


    ball_y = (
        BALL_START_Y
        +
        (
            235 -
            BALL_START_Y
        )
        * eased
    )


    ball_radius = (
        29 -
        15 * eased
    )


    if progress >= 1:

        # ------------------------------------------
        # GOALKEEPER SAVE RANGE
        # ------------------------------------------

        keeper_distance = abs(
            target_x -
            keeper_x
        )


        # Stronger shots are harder to save
        save_range = (
            75
            -
            shot_power * 0.35
        )

        save_range = max(
            28,
            save_range
        )


        saved = (
            keeper_distance
            <
            save_range
        )


        if saved:

            result_text = "SAVED!"

            streak = 0

            if miss_sound:
                miss_sound.stop()
                miss_sound.play()
        else:

            result_text = "GOAL!"

            goals += 1
            streak += 1

            if goal_sound:
                goal_sound.play()
                goal_sound.play()



        result_timer = (
            pygame.time.get_ticks()
        )

        game_state = STATE_RESULT


# ============================================================
# UPDATE KEEPER
# ============================================================

def update_keeper(dt):

    global keeper_x
    global keeper_direction


    keeper_x += (
        keeper_direction
        *
        KEEPER_SPEED
        *
        dt
    )


    if keeper_x >= KEEPER_MAX_X:

        keeper_x = KEEPER_MAX_X
        keeper_direction = -1


    elif keeper_x <= KEEPER_MIN_X:

        keeper_x = KEEPER_MIN_X
        keeper_direction = 1


# ============================================================
# MAIN LOOP
# ============================================================

running = True

while running:

    dt = (
        clock.tick(FPS)
        / 1000.0
    )


    # ========================================================
    # EVENTS
    # ========================================================

    for event in pygame.event.get():

        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:

            if event.key == pygame.K_ESCAPE:
                running = False


    # ========================================================
    # READ ESP32 DATA
    # ========================================================

    with serial_lock:

        target_aim = latest_aim

        kick = latest_kick

        latest_kick = None


    # ========================================================
    # SMOOTH AIM
    # ========================================================

    if game_state == STATE_READY:

        display_aim += (
            target_aim -
            display_aim
        ) * 0.18


    # ========================================================
    # KICK
    # ========================================================

    if kick is not None:

        start_shot(
            kick
        )


    # ========================================================
    # UPDATE
    # ========================================================

    update_keeper(dt)


    if game_state == STATE_SHOOTING:

        update_shot()


    elif game_state == STATE_RESULT:

        if (
            pygame.time.get_ticks()
            -
            result_timer
            >
            1400
        ):
            reset_ball()


    # ========================================================
    # DRAW
    # ========================================================

    screen.fill(
        (35, 120, 55)
    )


    draw_stadium()
    draw_pitch()
    draw_goal()
    draw_keeper(
        keeper_x
    )


    # Aim line only before shooting
    if game_state == STATE_READY:
        draw_aim_line()


    draw_football(
        ball_x,
        ball_y,
        ball_radius
    )


    draw_hud()
    draw_instruction()
    draw_result()


    pygame.display.flip()


pygame.quit()