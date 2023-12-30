
print('LOADING...')

import pyaudio
import numpy as np
import time
import os
from gpiozero import LED, Button

debounce_length = 0.03 #length in seconds of button debounce period

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
FORMAT = pyaudio.paInt16 #specifies bit depth (16-bit)
CHANNELS = 1 #mono audio
latency_in_milliseconds = int(parameters[2])
LATENCY = round((latency_in_milliseconds/1000) * (RATE/CHUNK)) #latency in buffers
INDEVICE = int(parameters[3]) #index (per pyaudio) of input device
OUTDEVICE = int(parameters[4]) #index of output device
overshoot_in_milliseconds = int(parameters[5]) #allowance in milliseconds for pressing 'stop recording' late
OVERSHOOT = round((overshoot_in_milliseconds/1000) * (RATE/CHUNK)) #allowance in buffers
MAXLENGTH = int(12582912 / CHUNK) #96mb of audio in total
SAMPLEMAX = 0.9 * (2**15) #maximum possible value for an audio sample (little bit of margin)
LENGTH = 0 #length of the first recording on track 1, all subsequent recordings quantized to a multiple of this.

print(str(RATE) + ' ' +  str(CHUNK))
print('NEW VERSION/nlatency correction (buffers): ' + str(LATENCY))
print('looking for devices ' + str(INDEVICE) + ' and ' + str(OUTDEVICE))

silence = np.zeros([CHUNK], dtype = np.int16) #a buffer containing silence

#mixed output (sum of audio from tracks) is multiplied by output_volume before being played.
#This is updated dynamically as max peak in resultant audio changes
output_volume = np.float16(1.0)

#multiplying by up_ramp and down_ramp gives fade-in and fade-out
down_ramp = np.linspace(1, 0, CHUNK)
up_ramp = np.linspace(0, 1, CHUNK)

def fade_in(buffer):
    '''
    fade_in() applies fade-in to a buffer
    '''
    np.multiply(buffer, up_ramp, out = buffer, casting = 'unsafe')


def fade_out(buffer):
    '''
    fade_out() applies fade-out to a buffer
    '''
    np.multiply(buffer, down_ramp, out = buffer, casting = 'unsafe')

pa = pyaudio.PyAudio()

class audioloop:
    def __init__(self):
        self.initialized = False
        self.length_factor = 1
        self.length = 0
        #self.main_audio and self.dub_audio contain audio data in arrays of CHUNKs.
        self.main_audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        #self.dub_audio contains the latest recorded dub. Clearing this achieves undo.
        self.dub_audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.readp = 0
        self.writep = 0
        self.is_recording = False
        self.is_playing = False
        self.is_waiting = False
        self.last_buffer_recorded = 0 #index of last buffer added
        self.preceding_buffer = np.zeros([CHUNK], dtype = np.int16)
        """
        Dub ratio must be reduced with each overdub to keep all overdubs at the same level while preventing clipping.
        first overdub is attenuated by a factor of 0.9, second by 0.81, etc.
        each time the existing audio is attenuated by a factor of 0.9.
        """
        self.dub_ratio = 1.0

    def increment_pointers(self):
        '''
        increment_pointers() increments pointers and, when restarting while recording, advances dub ratio
        '''
        if self.readp == self.length - 1:
            self.readp = 0
            if self.is_recording:
                self.dub_ratio = self.dub_ratio * 0.9
                print(self.dub_ratio)
        else:
            self.readp = self.readp + 1
        self.writep = (self.writep + 1) % self.length

    def initialize(self):
        '''
        initialize() raises self.length to closest integer multiple of LENGTH and initializes read and write pointers
        '''
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
        fade_out(self.main_audio[self.last_buffer_recorded]) #fade out the last recorded buffer
        preceding_buffer_copy = np.copy(self.preceding_buffer)
        fade_in(preceding_buffer_copy)
        self.main_audio[self.length - 1, :] += preceding_buffer_copy[:]
        #audio should be written ahead of where it is being read from, to compensate for input+output latency
        self.readp = (self.writep + LATENCY) % self.length
        self.initialized = True
        self.is_playing = True
        self.increment_pointers()

    def add_buffer(self, data):
        '''
        add_buffer() appends a new buffer unless loop is filled to MAXLENGTH
        expected to only be called before initialization
        '''
        if self.length >= (MAXLENGTH - 1):
            self.length = 0
            print('loop full')
            return
        self.main_audio[self.length, :] = np.copy(data)
        self.length = self.length + 1

    def toggle_mute(self):
        if self.is_playing:
            self.is_playing = False
        else:
            self.is_playing = True

    def is_restarting(self):
        if not self.initialized:
            return False
        if self.readp == 0:
            return True
        return False

    def read(self):
        '''
        read() reads and returns a buffer of audio from the loop

        if not initialized: Do nothing
        if initialized but muted: Just increment pointers
        if initialized and playing: Read audio from the loop and increment pointers
        '''        
        if not self.initialized:
            return(silence)
        
        if not self.is_playing:
            self.increment_pointers()
            return(silence)
        
        tmp = self.readp
        self.increment_pointers()
        return(self.main_audio[tmp, :] + self.dub_audio[tmp, :])
    
    def dub(self, data, fade_in = False, fade_out = False):
        '''
        dub() overdubs an incoming buffer of audio to the loop at writep
        
        at writep:
        first, the buffer from dub_audio is mixed into main_audio
        next, the buffer in dub_audio is overwritten with the incoming buffer
        '''
        if not self.initialized:
            return
        datadump = np.copy(data)
        self.main_audio[self.writep, :] = self.main_audio[self.writep, :] * 0.9 + self.dub_audio[self.writep, :] * self.dub_ratio
        self.dub_audio[self.writep, :] = datadump[:]

    def clear(self):
        '''
        clear() clears the loop so that a new loop of the same or a different length can be recorded on the track
        '''
        self.main_audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.dub_audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.initialized = False
        self.is_playing = False
        self.is_recording = False
        self.is_waiting = False
        self.length_factor = 1
        self.length = 0
        self.readp = 0
        self.writep = 0
        self.last_buffer_recorded = 0
        self.preceding_buffer = np.zeros([CHUNK], dtype = np.int16)

    def undo(self):
        '''
        undo() resets dub_audio to silence
        '''
        self.dub_audio = np.zeros([MAXLENGTH, CHUNK], dtype = np.int16)
        self.is_recording = False
        self.is_waiting = False

    def clear_or_undo(self):
        '''
        clear if muted, undo if playing.
        '''
        if self.is_playing:
            self.undo()
        else:
            self.clear()
    
    def start_recording(self, previous_buffer):
        self.is_recording = True
        self.is_waiting = False
        self.preceding_buffer = np.copy(previous_buffer)

    def set_recording(self):
        '''
        set_recording() either starts or stops recording

        if initialized and recording, stop recording (dubbing)
        if uninitialized and recording, stop recording (appending) and initialize
        if initialized and not recording, set as "waiting to record"
        '''
        print('set_recording called')
        already_recording = False

        #if chosen track is currently recording, flag it
        if self.is_recording:
            already_recording = True

        #turn off recording
        if self.is_recording and not self.initialized:
            self.initialize()
        self.is_recording = False
        self.is_waiting = False

        #unless flagged, schedule recording. If chosen track was recording, then stop recording
        #like a toggle but with delayed enabling and instant disabling
        if not already_recording:
            self.is_waiting = True

#defining four audio loops. loops[0] is the master loop.
loops = (audioloop(), audioloop(), audioloop(), audioloop())

#while looping, prev_rec_buffer keeps track of the audio buffer recorded before the current one
prev_rec_buffer = np.zeros([CHUNK], dtype = np.int16)

def update_volume():
    '''
    update output volume to prevent mixing distortion due to sample overflow
    slow to run, so should be called on a different thread (e.g. a button callback function)
    '''
    global output_volume
    peak = np.max(
                  np.abs(
                          loops[0].main_audio.astype(np.int32)[:][:]
                        + loops[1].main_audio.astype(np.int32)[:][:]
                        + loops[2].main_audio.astype(np.int32)[:][:]
                        + loops[3].main_audio.astype(np.int32)[:][:]
                        + loops[0].dub_audio.astype(np.int32)[:][:]
                        + loops[1].dub_audio.astype(np.int32)[:][:]
                        + loops[2].dub_audio.astype(np.int32)[:][:]
                        + loops[3].dub_audio.astype(np.int32)[:][:]
                        )
                 )
    print('peak = ' + str(peak))
    if peak > SAMPLEMAX:
        output_volume = SAMPLEMAX / peak
    else:
        output_volume = 1
    print('output volume = ' + str(output_volume))

def show_status():
    '''
    show_status() checks which loops are recording/playing and lights up LEDs accordingly
    '''
    for i in range(4):
        if loops[i].is_recording:
            RECLEDS[i].on()
        else:
            RECLEDS[i].off()
        if loops[i].is_playing:
            PLAYLEDS[i].on()
        else:
            PLAYLEDS[i].off()

setup_is_recording = False #set to True when track 1 recording button is first pressed
setup_donerecording = False #set to true when first track 1 recording is done

play_buffer = np.zeros([CHUNK], dtype = np.int16) #buffer to hold mixed audio from all 4 tracks

def looping_callback(in_data, frame_count, time_info, status):
    global play_buffer
    global prev_rec_buffer
    global setup_donerecording
    global setup_is_recording
    global LENGTH
    current_rec_buffer = np.right_shift(np.frombuffer(in_data, dtype = np.int16), 2) #some input attenuation for overdub headroom purposes
    #SETUP: FIRST RECORDING
    #if setup is not done i.e. if the master loop hasn't been recorded to yet
    if not setup_donerecording:
        #if setup is currently recording, that recording action happens in the following lines
        if setup_is_recording:
            #if the max allowed loop length is exceeded, stop recording and start looping
            if LENGTH >= MAXLENGTH:
                print('Overflow')
                setup_donerecording = True
                setup_is_recording = False
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
        #update_volume()
        for loop in loops:
            if loop.is_waiting:
                loop.start_recording(prev_rec_buffer)
                print('Recording...')
    #if master loop is waiting just start recording without checking restart
    if loops[0].is_waiting and not loops[0].initialized:
            loops[0].start_recording(prev_rec_buffer)
    #if a loop is recording, check initialization and accordingly append or overdub
    for loop in loops:
        if loop.is_recording:
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
setup_is_recording = True
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
setup_is_recording = False
setup_donerecording = True
print(LENGTH)
loops[0].initialize()
print('length is ' + str(LENGTH))
#stop recording on track 1, light LEDs appropriately, then allow time for button release
loops[0].set_recording()
show_status()
time.sleep(0.5)

#UI do everything else

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
    RECBUTTONS[i].when_held = loops[i].clear_or_undo
    RECBUTTONS[i].when_pressed = loops[i].set_recording
    RECBUTTONS[i].when_released = update_volume
    PLAYBUTTONS[i].when_pressed = loops[i].toggle_mute

PLAYBUTTONS[3].when_held = finish
PLAYBUTTONS[0].when_held = restart_looper

#this while loop runs during the jam session.
while not finished:
    show_status()
    time.sleep(0.1)

pa.terminate()
print('Done...')
