import math
import utime
from machine import Pin, I2S, UART

machine.freq(300_000_000)
print(machine.freq())

# Initialize the button
button = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)

# ========= I2S (mono) =========
BCK = 26
LCK = 27
DIN = 28

FS = 13555      # sample rate
BITS = 16

# ========= MIDI =========
MIDI_UART_ID = 0
MIDI_RX_PIN = 17
MIDI_BAUD = 31250

# ========= Audio =========
AMP = 0.12
A = int(AMP * 32767)

# Small wavetable to avoid MemoryError
FRAC_BITS = 13              # TABLE_LEN = 8192
TABLE_LEN = 1 << FRAC_BITS
MOD = TABLE_LEN << FRAC_BITS

def note_to_hz(n):
    return 440.0 * (2.0 ** ((n - 69) / 12.0))

def inc_for_freq(f_hz):
    return int((f_hz * MOD) / FS)


# ---------- Default tables ----------
sine = [0] * TABLE_LEN
for i in range(TABLE_LEN):
    theta = (2.0 * math.pi * i) / TABLE_LEN
    sine[i] = int(A * math.sin(theta))

square = [0] * TABLE_LEN
for i in range(TABLE_LEN):
    theta = (2.0 * math.pi * i) / TABLE_LEN
    square[i] = A * 1 if theta < math.pi else A * -1

saw = [0] * TABLE_LEN
for i in range(TABLE_LEN):
    saw[i] = int(2 * A * (i / TABLE_LEN - 0.5))

tables = [sine, square, saw]
table_idx = 0
table = tables[table_idx]

# ---------- Button table cycling IRQ ----------
last_irq_ms = 0
def button_handler(pin):
    global table, tables, table_idx, last_irq_ms
    now = utime.ticks_ms()
    if utime.ticks_diff(now, last_irq_ms) > 350:
        last_irq_ms = now
        table_idx = (table_idx + 1) % 3
        table = tables[table_idx]

button.irq(trigger=machine.Pin.IRQ_FALLING, handler=button_handler)

# ---------- Biquad (Low-pass) with live CC control ----------
# CC75 -> cutoff frequency
# CC76 -> Q
fc_hz = 2000.0
q = 0.7071

b0 = b1 = b2 = 0.0
a1 = a2 = 0.0

z1 = 0.0
z2 = 0.0

def biquad_set_lpf(fc, Q):
    global b0, b1, b2, a1, a2, z1, z2

    nyq = FS * 0.5
    if fc < 10.0:
        fc = 10.0
    if fc > (nyq - 1.0):
        fc = nyq - 1.0
    if Q < 0.001:
        Q = 0.001

    w0 = 2.0 * math.pi * fc / FS
    cosw0 = math.cos(w0)
    sinw0 = math.sin(w0)
    alpha = sinw0 / (2.0 * Q)

    b0n = (1.0 - cosw0) / 2.0
    b1n = 1.0 - cosw0
    b2n = (1.0 - cosw0) / 2.0
    a0n = 1.0 + alpha
    a1n = -2.0 * cosw0
    a2n = 1.0 - alpha

    b0 = b0n / a0n
    b1 = b1n / a0n
    b2 = b2n / a0n
    a1 = a1n / a0n
    a2 = a2n / a0n

    # reset filter state on coefficient update
    #z1 = 0.0
    #z2 = 0.0

biquad_set_lpf(fc_hz, q)
prev_fc = fc_hz
prev_q = q

# CC mapping (0..127 -> parameter ranges)
def cc_to_fc(v):
    # Exponential mapping for musical-ish response
    # v=0 => 50 Hz, v=127 => ~nyquist*0.95
    nyq = FS * 0.5
    f_min = 50.0
    f_max = nyq * 0.95
    t = v / 127.0
    # exponential interpolation
    return f_min * (f_max / f_min) ** t

def cc_to_q(v):
    # v=0 => 0.1, v=127 => 8.0
    return 0.1 + (v / 127.0) * (8.0 - 0.1)

# ---------- I2S init ----------
i2s = I2S(
    0,
    sck=Pin(BCK),
    ws=Pin(LCK),
    sd=Pin(DIN),
    mode=I2S.TX,
    bits=BITS,
    format=I2S.MONO,
    rate=FS,
    ibuf=2048
)

# ---------- UART MIDI RX (POLLED) ----------
uart = UART(MIDI_UART_ID, baudrate=MIDI_BAUD)
uart.init(MIDI_BAUD, bits=8, parity=None, stop=1, rx=Pin(MIDI_RX_PIN))

# ---------- MIDI parser (Note On/Off + CC on CC75/CC76) ----------
status = 0
need = 0
note_number = 0

def process_midi_byte(b):
    global status, need, note_number
    global inc, phase
    global vca_target_amplitude, active, note_played
    global fc_hz, q

    if b & 0x80:
        status = b
        msg_type = status & 0xF0

        # Channel voice:
        # 0x80 note off: 2 data bytes
        # 0x90 note on : 2 data bytes
        # 0xB0 CC      : 2 data bytes
        if msg_type in (0x80, 0x90, 0xB0):
            need = 2
        else:
            need = 0
        return

    if need == 0:
        return

    # data byte 1
    if need == 2:
        note_number = b  # for note msgs: note, for CC: controller #
        need = 1
        return

    # data byte 2
    data2 = b
    msg_type = status & 0xF0

    if msg_type == 0x80:
        # Note Off
        if note_number == note_played:
            vca_target_amplitude = 0.0
            need = 0
        return

    if msg_type == 0x90:
        # Note On (velocity 0 treated as off)
        if data2 == 0:
            if note_number == note_played:
                vca_target_amplitude = 0.0
        else:
            note_played = note_number
            vca_target_amplitude = data2 / 127.0
            inc = inc_for_freq(note_to_hz(note_number))
            #phase = 0  # uncomment if you want consistent phase restarts
        need = 0
        return

    if msg_type == 0xB0:
        # CC: note_number is controller number, data2 is value
        cc = note_number
        val = data2

        # CC75 cutoff, CC76 Q
        if cc == 75:
            fc_hz = cc_to_fc(val)
        elif cc == 76:
            q = cc_to_q(val)

        need = 0
        return

    need = 0

# ---------- Voice / oscillator / envelope ----------
note_played = 0
phase = 0
inc = inc_for_freq(440.0)

vca_current_amplitude = 0.0
vca_target_amplitude = 0.0

print("Wavetable synth (mono) with LPF. MIDI: Note On/Off; CC75 cutoff; CC76 Q.")

# ---------- Audio loop ----------
N = 64
buf = bytearray(N * 2)

# ---------- Envelope times (seconds) ----------
ATTACK_S = 0.05
RELEASE_S = 0.2

dt_s = N / FS
attack_step = dt_s / ATTACK_S if ATTACK_S > 0 else 1.0
release_step = dt_s / RELEASE_S if RELEASE_S > 0 else 1.0

while True:
    # Recompute filter coefficients if CC updated globals
    if fc_hz != prev_fc or q != prev_q:
        biquad_set_lpf(fc_hz, q)
        prev_fc = fc_hz
        prev_q = q

    # vca envelope update
    if vca_current_amplitude < vca_target_amplitude:
        vca_current_amplitude += attack_step
        if vca_current_amplitude > vca_target_amplitude:
            vca_current_amplitude = vca_target_amplitude
    elif vca_current_amplitude > vca_target_amplitude:
        vca_current_amplitude -= release_step
        if vca_current_amplitude < vca_target_amplitude:
            vca_current_amplitude = vca_target_amplitude

    # Drain limited MIDI per loop so audio stays steady, read only few bytes per loop to avoid sount output drops.
    data = uart.read(4)
    if data:
        for b in data:
            process_midi_byte(b)

    out = 0
    phase_local = phase

    # local copies for speed
    z1_local = z1
    z2_local = z2

    b0_l = b0
    b1_l = b1
    b2_l = b2
    a1_l = a1
    a2_l = a2
    vca_l = vca_current_amplitude

    for _ in range(N):
        idx = (phase_local >> FRAC_BITS) & (TABLE_LEN - 1)
        x = table[idx]

        # biquad DF-I
        y = b0_l * x + z1_local
        z1_local = b1_l * x + z2_local - a1_l * y
        z2_local = b2_l * x - a2_l * y

        s = int(y * vca_l)

        # clip to int16
        if s > 32767:
            s = 32767
        elif s < -32768:
            s = -32768

        lo = (s & 0xFF)
        hi = ((s >> 8) & 0xFF)
        buf[out] = lo
        buf[out + 1] = hi
        out += 2

        phase_local += inc
        if phase_local >= MOD:
            phase_local -= MOD

    phase = phase_local
    z1 = z1_local
    z2 = z2_local

    i2s.write(buf)

