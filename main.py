
print('LOADING...')

import pyaudio
import numpy as np
import time

#get configuration (audio settings etc.) from file
settings_file = open('Config/settings.prt', 'r')
parameters = settings_file.readlines()
settings_file.close()

RATE = int(parameters[0]) #sample rate
CHUNK = int(parameters[1]) #buffer size
print(str(RATE) + ' ' +  str(CHUNK))
FORMAT = pyaudio.paInt16 #specifies bit depth (16-bit)
CHANNELS = 1 #mono audio
latency_in_milliseconds = int(parameters[2])
LATENCY = round((latency_in_milliseconds/1000) * (RATE/CHUNK)) #latency in buffers
print('latency correction (buffers): ' + str(LATENCY))
INDEVICE = int(parameters[3]) #index (per pyaudio) of input device
OUTDEVICE = int(parameters[4]) #index of output device
print('looking for devices ' + str(INDEVICE) + ' and ' + str(OUTDEVICE))
overshoot_in_milliseconds = int(parameters[5]) #allowance in milliseconds for pressing 'stop recording' late
OVERSHOOT = LATENCY = round((overshoot_in_milliseconds/1000) * (RATE/CHUNK)) #allowance in buffers
MAXLENGTH = int(12582912 / CHUNK) #96mb of audio in total
LENGTH = 0 #length of the first loop, value set during first record

silence = np.zeros([CHUNK], dtype = np.int16) #a buffer containing silence

CROSSSYNC = 0.5 #something ad-hoc to improve sync between loops

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
        self.iswaiting = False
        #dub ratio must be reduced with each overdub to keep all overdubs at the same level while preventing clipping.
        #first overdub is attenuated by a factor of 0.9, second by 0.81, etc.
        #each time the existing audio is attenuated by a factor of 0.9
        self.dub_ratio = 1.0
    #incptrs() increments pointers and, when restarting while recording, advances dub ratio
    def incptrs(self):
        if self.readp == self.length - 1:
            self.readp = 0
            if self.isrecording:
                self.dub_ratio = self.dub_ratio * 0.9
                print(self.dub_ratio)
        else:
            self.readp = self.readp + 1
        self.writep = (self.writep + 1) % self.length
    #initialize() raises self.length to closest integer multiple of LENGTH and initializes read and write pointers
    def initialize(self):
        if self.initialized:
            print('redundant initialization')
            return
        self.writep = self.length - 1
        self.length_factor = (int((self.length - OVERSHOOT) / LENGTH) + 1)
        self.length = self.length_factor * LENGTH
        print('length ' + str(self.length))
        #self.writep = (int(self.writep + LATENCY * CROSSSYNC)) % self.length #something ad-hoc to improve sync between tracks
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
        self.incptrs()
    #dump_and_initialize() creates self.audio all at once by copying data into it
    def dump_and_initialize(self, data, length_in_buffers):
        self.audio = np.copy(data)
        self.length = length_in_buffers
        self.writep = self.length - 1
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
    #add_buffer() appends a new buffer unless loop is filled to MAXLENGTH
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
    def is_restarting(self):
        if not self.initialized:
            return False
        if self.readp == 0:
            return True
        return False
    #read() reard and returns a buffer of audio from the loop
    def read(self):
        #if not initialized do nothing
        if not self.initialized:
            return(silence)
        #if initialized but muted just increment pointers
        if not self.isplaying:
            self.incptrs()
            return(silence)
        #if initialized and playing, read audio from the loop and increment pointers
        tmp = self.readp
        self.incptrs()
        return(self.audio[tmp, :])
    #dub() mixes an incoming buffer of audio with the one at writep
    def dub(self, data):
        if not self.initialized:
            return
        datadump = np.frombuffer(data, dtype = np.int16)
        self.audio[self.writep, :] = self.audio[self.writep, :] * 0.9 + datadump[:] * self.dub_ratio
    #clear() clears the loop so that a new loop of the same or a different length can be recorded on the track
    def clear(self):
        self.initialized = False
        self.isplaying = False
        self.isrecording = False
        self.iswaiting = False
        self.length_factor = 1
        self.length = 0
        self.readp = 0
        self.writep = 0

loop1 = audioloop()
loop2 = audioloop()
loop3 = audioloop()
loop4 = audioloop()
loops = (loop1, loop2, loop3, loop4)

#set_recording() schedules a loop to start recording when loop1 next restarts
def set_recording(loop_number):
    global loops
    already_recording = False
    if not loop_number in (1, 2, 3, 4):
        for loop in loops:
            loop.isrecording = False
            loop.iswaiting = False
        return
    if loops[loop_number-1].isrecording:
        already_recording = True
    for loop in loops:
        if loop.isrecording and not loop.initialized:
            loop.initialize()
        loop.isrecording = False
        loop.iswaiting = False
    if not already_recording: #calling set_recording() if already recording just disables recording
        loops[loop_number-1].iswaiting = True

setup_isrecording = False #set to True when track 1 recording button is first pressed

def setup_callback(in_data, frame_count, time_info, status):
    global LENGTH
    if setup_isrecording:
        if LENGTH >= MAXLENGTH: #if the max looping time is being exceeded, truncate the loop
            print('setup stream loop overflow')
            return(silence, pyaudio.paComplete)
        tmp_clip[LENGTH, :] = np.frombuffer(in_data, dtype = np.int16) #append incoming buffer to tmp-clip
        LENGTH = LENGTH + 1
        return(silence, pyaudio.paContinue)
    else:
        return(silence, pyaudio.paContinue)

play_buffer = np.zeros([CHUNK], dtype = np.int16) #buffer to hold mixed audio from all 4 tracks

def looping_callback(in_data, frame_count, time_info, status):
    global play_buffer
    #when loop1 restarts, start recording on any tracks that are waiting
    if loop1.is_restarting():
        for loop in loops:
            if loop.iswaiting:
                loop.isrecording = True
                loop.iswaiting = False
                print('Recording...')
    #if loop1 is recording, overdub
    if loop1.isrecording:
        loop1.dub(in_data)
    #if any other loop is recording, check initialization and accordingly add or overdub
    for loop in (loop2, loop3, loop4):
        if loop.isrecording:
            if loop.initialized:
                loop.dub(in_data)
            else:
                loop.add_buffer(in_data)

    play_buffer[:] = (loop1.read()[:] + loop2.read()[:] + loop3.read()[:] + loop4.read()[:])/4
    return(play_buffer, pyaudio.paContinue)

setup_stream = pa.open(
    format = FORMAT,
    channels = CHANNELS,
    rate = RATE,
    input = True,
    output = False,
    input_device_index = INDEVICE,
    output_device_index = OUTDEVICE,
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
    input_device_index = INDEVICE,
    output_device_index = OUTDEVICE,
    frames_per_buffer = CHUNK,
    start = False,
    stream_callback = looping_callback
)

setup_stream.start_stream()
time.sleep(1)

print('ready')

def showstatus():
    print('unmuted:')
    print(str(loop1.isplaying) + str(loop2.isplaying) + str(loop3.isplaying) + str(loop4.isplaying))
    print('recording')
    print(str(loop1.iswaiting) + str(loop2.iswaiting) + str(loop3.iswaiting) + str(loop4.iswaiting))

input()
setup_isrecording = True
input()
setu_isrecording = False
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
    elif ans == '1':
        loop1.clear()
    elif ans == '2':
        loop2.clear()
    elif ans == '3':
        loop3.clear()
    elif ans == '4':
        loop4.clear()
    else:
        set_recording(0)

looping_stream.stop_stream()
pa.terminate()
