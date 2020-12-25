print('LOADING...')

import pyaudio
import numpy as np
import time

RATE = 44100
CHUNK = 256
FORMAT = pyaudio.paInt16
CHANNELS = 1

LATENCY = 7
OVERSHOOT = 30 #allowance in buffers for pressing the button late

MAXLENGTH = 3000 #Assuming about a minute of looping at buffer size 512

LENGTH = 0 #length of the first loop, set during first record

silence = np.zeros([CHUNK], dtype = np.int16)

#tmp_clip holds the first loop recorded before dumping to loop1
tmp_clip = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)

pa = pyaudio.PyAudio()

class audioloop:
    def __init__(self):
        self.initialized = False
        self.length_factor = 1
        self.length = 0
        self.audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.readp = 0
        self.writep = 0
        self.isrecording = False
        self.isplaying = False
        self.dub_ratio = 1.0
    def dump_and_initialize(self, data, length_in_buffers):
        self.audio = np.copy(data)
        self.length = length_in_buffers
        self.writep = self.length
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
    def incptrs(self): #increments pointers and advances dub factor if restarting and recording
        if self.readp == self.length:
            self.readp = 0
            if self.isrecording:
                self.dub_ratio = self.dub_ratio * 0.9
                print(self.dub_ratio)
        else:
            self.readp = self.readp + 1
        self.writep = (self.writep + 1) % self.length
    #initialize() raises self.length to closest multiple of LENGTH and initializes read and write pointers
    def initialize(self):
        if self.initialized:
            print('redundant initialization')
            return
        self.writep = self.length
        self.length_factor = (int((self.length - OVERSHOOT) / LENGTH) + 1)
        self.length = self.length_factor * LENGTH
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
    #add_buffer() appends a new buffer as long as loop is not filled to MAXLENGTH
    def add_buffer(self, data):
        if self.length >= (MAXLENGTH - 1):
            self.length = 0
            print('loop full')
            return
        self.audio[self.length, :] = np.frombuffer(data, dtype = np.int16)
        self.length = self.length + 1
    def toggle_mute(self):
        if self.isplaying:
            self.isplaying = False
        else:
            self.isplaying = True
    def read(self):
        if not self.initialized:
            return(silence)
        if not self.isplaying:
            self.incptrs()
            return(silence)
        tmp = self.readp
        self.incptrs()
        return(self.audio[tmp, :])
    def dub(self, data):
        if not self.initialized:
            return
        datadump = np.frombuffer(data, dtype = np.int16)
        for i in range(CHUNK):
            self.audio[self.writep, i] = self.audio[self.writep, i] * 0.9 + datadump[i] * self.dub_ratio

loop1 = audioloop()
loop2 = audioloop()
loop3 = audioloop()
loop4 = audioloop()
loops = (loop1, loop2, loop3, loop4)

def set_recording(loop_number):
    global loops
    for loop in loops:
        if loop.isrecording and not loop.initialized:
            loop.initialize()
        loop.isrecording = False
    if loop_number in (1, 2, 3, 4):
        loops[loop_number-1].isrecording = True

def warmup_callback(in_data, frame_count, time_info, status):
    return(silence, pyaudio.paContinue)

def setup_callback(in_data, frame_count, time_info, status):
    global LENGTH
    if LENGTH >= MAXLENGTH:
        print('setup stream loop overflow')
        return(silence, pyaudio.paComplete)
    tmp_clip[LENGTH, :] = np.frombuffer(in_data, dtype = np.int16)
    LENGTH = LENGTH + 1
    return(silence, pyaudio.paContinue)

play_buffer = np.zeros([CHUNK], dtype = np.int16)

def looping_callback(in_data, frame_count, time_info, status):
    if loop1.isrecording:
        loop1.dub(in_data)
    elif loop2.isrecording:
        if loop2.initialized:
            loop2.dub(in_data)
        else:
            loop2.add_buffer(in_data)
    elif loop3.isrecording:
        if loop3.initialized:
            loop3.dub(in_data)
        else:
            loop3.add_buffer(in_data)
    elif loop4.isrecording:
        if loop4.initialized:
            loop4.dub(in_data)
        else:
            loop4.add_buffer(in_data)

    play_buffer[:] = (loop1.read()[:] + loop2.read()[:] + loop3.read()[:] + loop4.read()[:])/4
    return(play_buffer, pyaudio.paContinue)

#warmup stream wakes up the sound card or something. Prevents crackling in first recording on linux.
warmup_stream = pa.open(
    format = FORMAT,
    channels = CHANNELS,
    rate = RATE,
    input = True,
    output = True,
    frames_per_buffer = CHUNK,
    start = False,
    stream_callback = warmup_callback
)

setup_stream = pa.open(
    format = FORMAT,
    channels = CHANNELS,
    rate = RATE,
    input = True,
    output = False,
    frames_per_buffer = CHUNK,
    start = False,
    stream_callback = setup_callback
)

looping_stream = pa.open(
    format = FORMAT,
    channels = CHANNELS,
    rate = RATE,
    input = True,
    output = True,
    frames_per_buffer = CHUNK,
    start = False,
    stream_callback = looping_callback
)

warmup_stream.start_stream()
time.sleep(1)
warmup_stream.stop_stream()

print('ready')

def showstatus():
    print('unmuted:')
    print(str(loop1.isplaying) + str(loop2.isplaying) + str(loop3.isplaying) + str(loop4.isplaying))
    print('recording')
    print(str(loop1.isrecording) + str(loop2.isrecording) + str(loop3.isrecording) + str(loop4.isrecording))

input()
setup_stream.start_stream()
input()
setup_stream.stop_stream()
loop1.dump_and_initialize(tmp_clip, LENGTH)
looping_stream.start_stream()

print('length is ' + str(LENGTH))

while True:
    showstatus()
    ans = input()
    print(ans)
    if ans == 'q':
        loop1.toggle_mute()
    elif ans == 'w':
        loop2.toggle_mute()
    elif ans == 'e':
        loop3.toggle_mute()
    elif ans == 'r':
        loop4.toggle_mute()
    elif ans == 'x':
        break
    elif ans == 'a':
        set_recording(1)
    elif ans == 's':
        set_recording(2)
    elif ans == 'd':
        set_recording(3)
    elif ans == 'f':
        set_recording(4)
    else:
        set_recording(0)

looping_stream.stop_stream()
pa.terminate()
