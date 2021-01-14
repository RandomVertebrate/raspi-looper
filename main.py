
print('LOADING...')

import pyaudio
import numpy as np
import time
from gpiozero import LED, Button

#defining buttons and LEDs
PLAYLEDS = (LED(2), LED(3), LED(4), LED(17))
RECLEDS = (LED(27), LED(22), LED(10), LED(9))
PLAYBUTTONS = (Button(11), Button(5), Button(6), Button(13))
RECBUTTONS = (Button(19), Button(26), Button(21), Button(20))

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
OVERSHOOT = round((overshoot_in_milliseconds/1000) * (RATE/CHUNK)) #allowance in buffers
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
        print('initialize called')
        if self.initialized:
            print('redundant initialization')
            return
        self.writep = self.length - 1
        self.length_factor = (int((self.length - OVERSHOOT) / LENGTH) + 1)
        self.length = self.length_factor * LENGTH
        print('length ' + str(self.length))
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
        self.incptrs()
    #dump_and_initialize() creates self.audio all at once by copying data into it
    def dump_and_initialize(self, data, length_in_buffers):
        print('dump called')
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
        self.audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
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
def set_recording(loop_number = 0):
    print('set_recording called')
    global loops
    already_recording = False
    #if invalid input just stop recording on all tracks, initialize track if needed and return
    if not loop_number in (1, 2, 3, 4):
        print('invalid')
        for loop in loops:
            if loop.isrecording and not loop.initialized:
                loop.initialize()
            loop.isrecording = False
            loop.iswaiting = False
        return
    #if chosen track is currently recording flag it
    if loops[loop_number-1].isrecording:
        already_recording = True
    #turn off recording on all tracks
    for loop in loops:
        if loop.isrecording and not loop.initialized:
            loop.initialize()
        loop.isrecording = False
        loop.iswaiting = False
    #unless flagged, schedule recording. If chosen track was recording, then stop recording
    #like a toggle but with delayed enabling and instant disabling
    if not already_recording:
        loops[loop_number-1].iswaiting = True

setup_isrecording = False #set to True when track 1 recording button is first pressed
setup_donerecording = False #set to true when first track 1 recording is done

def showstatus():
    for i in range(4):
        if loops[i].isrecording:
            RECLEDS[i].on()
        else:
            RECLEDS[i].off()
        if loops[i].isplaying:
            PLAYLEDS[i].on()
        else:
            PLAYLEDS[i].off()

play_buffer = np.zeros([CHUNK], dtype = np.int16) #buffer to hold mixed audio from all 4 tracks

def looping_callback(in_data, frame_count, time_info, status):
    global play_buffer
    global setup_donerecording
    global setup_isrecording
    global LENGTH
    #if setup is not done recording
    #i.e. if the first loop hasn't been recorded yet, nothing else happens
    if not setup_donerecording:
        if setup_isrecording:
            #if the max allowed loop length is exceeded, stop recording and start looping
            if LENGTH >= MAXLENGTH:
                print('Overflow')
                setup_donerecording = True
                setup_isrecording = False
                return(silence, pyaudio.paContinue)
            #append incoming audio to tmp_clip
            tmp_clip[LENGTH, :] = np.frombuffer(in_data, dtype = np.int16)
            LENGTH = LENGTH + 1
            return(silence, pyaudio.paContinue)
        #if first loop not currently recording and not yet recorded just wait
        else:
            return(silence, pyaudio.paContinue)
    #execution ony reaches here if first loop finished recording.
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

#now initializing looping_stream (the only audio stream)
looping_stream = pa.open(
    format = FORMAT,
    channels = CHANNELS,
    rate = RATE,
    input = True,
    output = True,
    input_device_index = INDEVICE,
    output_device_index = OUTDEVICE,
    frames_per_buffer = CHUNK,
    start = True,
    stream_callback = looping_callback
)

#UI record first loop

time.sleep(3)
print('ready')
for led in RECLEDS:
    led.on()
for led in PLAYLEDS:
    led.on()

RECBUTTONS[0].wait_for_press()
setup_isrecording = True
for i in range(1, 4):
    RECLEDS[i].off()
for led in PLAYLEDS:
    led.off()
time.sleep(1) #allowing time for button release
RECBUTTONS[0].wait_for_press()
setup_isrecording = False
setup_donerecording = True
print(LENGTH)
loop1.dump_and_initialize(tmp_clip, LENGTH)
print('length is ' + str(LENGTH))

showstatus()

#UI do everything else

def set_rec_1():
    set_recording(1)
def set_rec_2():
    set_recording(2)
def set_rec_3():
    set_recording(3)
def set_rec_4():
    set_recording(4)

finished = False
def finish():
    global finished
    finished = True

for i in range(4):
    RECBUTTONS[i].when_held = loops[i].clear
    PLAYBUTTONS[i].when_pressed = loops[i].toggle_mute

RECBUTTONS[0].when_pressed = set_rec_1
RECBUTTONS[1].when_pressed = set_rec_2
RECBUTTONS[2].when_pressed = set_rec_3
RECBUTTONS[3].when_pressed = set_rec_4

PLAYBUTTONS[3].when_held = finish

while not finished:
    time.sleep(0.3)
    showstatus()
