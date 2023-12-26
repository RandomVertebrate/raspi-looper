
print('LOADING...')

import pyaudio
import numpy as np
import time
import os
from gpiozero import LED, Button

debounce_length = 0.1 #length in seconds of button debounce period

#defining buttons and LEDs
PLAYLEDS = (LED(2), LED(3), LED(4), LED(17))
RECLEDS = (LED(27), LED(22), LED(10), LED(9))
PLAYBUTTONS = (Button(11, bounce_time = debounce_length),
               Button(5, bounce_time = debounce_length),
               Button(6, bounce_time = debounce_length),
               Button(13, bounce_time = debounce_length))
RECBUTTONS = (Button(19, bounce_time = debounce_length),
              Button(26, bounce_time = debounce_length),
              Button(21, bounce_time = debounce_length),
              Button(20, bounce_time = debounce_length))

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
SAMPLEMAX = 0.9 * (2**15) #maximum possible value for an audio sample (little bit of margin)
LENGTH = 0 #length of the first recording on track 1, all subsequent recordings quantized to a multiple of this.

silence = np.zeros([CHUNK], dtype = np.int16) #a buffer containing silence

#mixed output (sum of audio from tracks) is multiplied by output_volume before being played.
#This is updated dynamically as max peak in resultant audio changes
output_volume = np.float16(1.0)

#multiplying by upramp and downramp gives fade-in and fade-out
downramp = np.linspace(1, 0, CHUNK)
upramp = np.linspace(0, 1, CHUNK)
#fadein() applies fade-in to a buffer
def fadein(buffer):
    np.multiply(buffer, upramp, out = buffer, casting = 'unsafe')
#fadeout() applies fade-out to a buffer
def fadeout(buffer):
    np.multiply(buffer, downramp, out = buffer, casting = 'unsafe')

pa = pyaudio.PyAudio()

class audioloop:
    def __init__(self):
        self.initialized = False
        self.length_factor = 1
        self.length = 0
        #self.audio is a 2D array of samples, each row is a buffer's worth of audio
        self.audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.readp = 0
        self.writep = 0
        self.isrecording = False
        self.isplaying = False
        self.iswaiting = False
        self.last_buffer_recorded = 0 #index of last buffer added
        self.preceding_buffer = np.zeros([CHUNK], dtype = np.int16)
        #dub ratio must be reduced with each overdub to keep all overdubs at the same level while preventing clipping.
        #first overdub is attenuated by a factor of 0.9, second by 0.81, etc.
        #each time the existing audio is attenuated by a factor of 0.9
        #in this way infinite overdubs of amplitude x result in total amplitude 9x.
        self.dub_ratio = 1.0
        self.rec_just_pressed = False
        self.play_just_pressed = False
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
        self.last_buffer_recorded = self.writep
        self.length_factor = (int((self.length - OVERSHOOT) / LENGTH) + 1)
        self.length = self.length_factor * LENGTH
        print('length ' + str(self.length))
        print('last buffer recorded ' + str(self.last_buffer_recorded))
        #crossfade
        fadeout(self.audio[self.last_buffer_recorded]) #fade out the last recorded buffer
        preceding_buffer_copy = np.copy(self.preceding_buffer)
        fadein(preceding_buffer_copy)
        self.audio[self.length - 1, :] += preceding_buffer_copy[:]
        #audio should be written ahead of where it is being read from, to compensate for input+output latency
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.isplaying = True
        self.incptrs()
    #add_buffer() appends a new buffer unless loop is filled to MAXLENGTH
    #expected to only be called before initialization
    def add_buffer(self, data):
        if self.length >= (MAXLENGTH - 1):
            self.length = 0
            print('loop full')
            return
        self.audio[self.length, :] = np.copy(data)
        self.length = self.length + 1
    def toggle_mute(self):
        #toggle mute
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
    #read() reads and returns a buffer of audio from the loop
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
    def dub(self, data, fade_in = False, fade_out = False):
        if not self.initialized:
            return
        datadump = np.copy(data)
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
        self.last_buffer_recorded = 0
        self.preceding_buffer = np.zeros([CHUNK], dtype = np.int16)
        self.rec_just_pressed = False
        self.play_just_pressed = False
    def start_recording(self, previous_buffer):
        self.isrecording = True
        self.iswaiting = False
        self.preceding_buffer = np.copy(previous_buffer)

#defining four audio loops. loops[0] is the master loop.
loops = (audioloop(), audioloop(), audioloop(), audioloop())

#while looping, prev_rec_buffer keeps track of the audio buffer recorded before the current one
prev_rec_buffer = np.zeros([CHUNK], dtype = np.int16)

#update output volume to prevent mixing distortion due to sample overflow
def updatevolume():
    global output_volume
    peak = np.max(
                  np.abs(
                          loops[0].audio.astype(np.int32)[:][:]
                        + loops[1].audio.astype(np.int32)[:][:]
                        + loops[2].audio.astype(np.int32)[:][:]
                        + loops[3].audio.astype(np.int32)[:][:]
                        )
                 )
    print('peak = ' + str(peak))
    if peak > SAMPLEMAX:
        output_volume = SAMPLEMAX / peak
    else:
        output_volume = 1
    print('output volume = ' + str(output_volume))

#showstatus() checks which loops are recording/playing and lights up LEDs accordingly
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

#set_recording() schedules a loop to start recording, for when master loop next restarts
def set_recording(loop_number = 0):
    global loops
    #if just pressed do nothing
    if loops[loop_number-1].rec_just_pressed:
        return
    print('set_recording called')
    already_recording = False
    #if invalid input, do nothing
    if not loop_number in (1, 2, 3, 4):
        print('invalid loop number passed to set_recording')
        return;
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
    if already_recording: #then set_recording() was called to finish the recording, i.e. new audio just got added.
        showstatus() #so that delay due to volume updation doesn't affect LED indicator update speed
        updatevolume()
    else: #set_recording was called to actually prep the track to start recording
        loops[loop_number-1].iswaiting = True

setup_isrecording = False #set to True when track 1 recording button is first pressed
setup_donerecording = False #set to true when first track 1 recording is done

play_buffer = np.zeros([CHUNK], dtype = np.int16) #buffer to hold mixed audio from all 4 tracks

def looping_callback(in_data, frame_count, time_info, status):
    global play_buffer
    global prev_rec_buffer
    global setup_donerecording
    global setup_isrecording
    global LENGTH
    current_rec_buffer = np.copy(np.frombuffer(in_data, dtype = np.int16))
    #SETUP: FIRST RECORDING
    #if setup is not done i.e. if the master loop hasn't been recorded to yet
    if not setup_donerecording:
        #if setup is currently recording, that recording action happens in the following lines
        if setup_isrecording:
            #if the max allowed loop length is exceeded, stop recording and start looping
            if LENGTH >= MAXLENGTH:
                print('Overflow')
                setup_donerecording = True
                setup_isrecording = False
                return(silence, pyaudio.paContinue)
            #otherwise append incoming audio to master loop, increment LENGTH and continue
            loops[0].add_buffer(current_rec_buffer)
            LENGTH = LENGTH + 1
            return(silence, pyaudio.paContinue)
        #if setup not done and not currently happening then just wait
        else:
            return(silence, pyaudio.paContinue)
    #execution ony reaches here if setup (first loop record and set LENGTH) finished.
    #when master loop restarts, start recording on any other tracks that are waiting
    if loops[0].is_restarting():
        for loop in loops:
            if loop.iswaiting:
                loop.start_recording(prev_rec_buffer)
                print('Recording...')
    #if master loop is waiting just start recording without checking restart
    if loops[0].iswaiting and not loops[0].initialized:
            loops[0].start_recording(prev_rec_buffer)
    #if a loop is recording, check initialization and accordingly append or overdub
    for loop in loops:
        if loop.isrecording:
            if loop.initialized:
                loop.dub(current_rec_buffer)
            else:
                loop.add_buffer(current_rec_buffer)
    #add to play_buffer only one-fourth of each audio signal times the output_volume
    play_buffer[:] = np.multiply((
                                   loops[0].read().astype(np.int32)[:]
                                 + loops[1].read().astype(np.int32)[:]
                                 + loops[2].read().astype(np.int32)[:]
                                 + loops[3].read().astype(np.int32)[:]
                                 ), output_volume, out= None, casting = 'unsafe').astype(np.int16)
    #current buffer will serve as previous in next iteration
    prev_rec_buffer = np.copy(current_rec_buffer)
    #play mixed audio and move on to next iteration
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

#audio stream has now been started and the callback function is running in a background thread.
#first, we give the stream some time to properly start up
time.sleep(3)
#then we turn on all lights to indicate that looper is ready to start looping
print('ready')
for led in RECLEDS:
    led.on()
for led in PLAYLEDS:
    led.on()

#once all LEDs are on, we wait for the master loop record button to be pressed
RECBUTTONS[0].wait_for_press()
#when the button is pressed, set the flag... looping_callback will see this flag. Also start recording on track 1
setup_isrecording = True
loops[0].start_recording(prev_rec_buffer)

#turn off all LEDs except master loop record
for i in range(1, 4):
    RECLEDS[i].off()
for led in PLAYLEDS:
    led.off()

#allow time for button release, otherwise pressing the button once will start and stop the recording
time.sleep(0.5)
#now wait for button to be pressed again, then stop recording and initialize master loop
RECBUTTONS[0].wait_for_press()
setup_isrecording = False
setup_donerecording = True
print(LENGTH)
loops[0].initialize()
print('length is ' + str(LENGTH))
#stop recording on track 1, light LEDs appropriately, then allow time for button release
set_recording(1)
showstatus()
time.sleep(0.5)

#UI do everything else

#the 4 following functions are here because you seemingly can't pass parameters in button-press event definitions
def set_rec_1():
    set_recording(1)
def set_rec_2():
    set_recording(2)
def set_rec_3():
    set_recording(3)
def set_rec_4():
    set_recording(4)

finished = False
#calling finish() will set finished flag, allowing program to break from loop at end of script and exit
def finish():
    global finished
    finished = True

#restart_looper() restarts this python script
def restart_looper():
    pa.terminate() #needed to free audio device for reuse
    os.execlp('python3', 'python3', 'main.py') #replaces current process with a new instance of the same script

#now defining functions of all the buttons during jam session...

for i in range(4):
    RECBUTTONS[i].when_held = loops[i].clear
    PLAYBUTTONS[i].when_pressed = loops[i].toggle_mute
    
RECBUTTONS[0].when_pressed = set_rec_1
RECBUTTONS[1].when_pressed = set_rec_2
RECBUTTONS[2].when_pressed = set_rec_3
RECBUTTONS[3].when_pressed = set_rec_4

PLAYBUTTONS[3].when_held = finish
PLAYBUTTONS[0].when_held = restart_looper

#this while loop runs during the jam session.
while not finished:
    showstatus()
    time.sleep(0.3)

pa.terminate()
print('Done...')
