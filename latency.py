import pyaudio
import numpy as np
import time

settings_file = open('Config/settings.prt', 'r')
parameters = settings_file.readlines()
settings_file.close()

RATE = int(parameters[0]) #sample rate
CHUNK = int(parameters[1]) #buffer size
FORMAT = pyaudio.paInt16
CHANNELS = 1
INDEVICE = int(parameters[3])
OUTDEVICE = int(parameters[4])
CLIPLENGTH = 100 #probably ok as constant.

click_ang_fr = 0.5 #angular frequency of test click in radians per sample. Probably ok as constant.

pa = pyaudio.PyAudio()

silence = np.zeros(CHUNK, dtype = np.int16)

cos_arr = np.empty(CHUNK, dtype = float)                         #to store values of cos(i omega) at all relevant i
for i in range(CHUNK):
    cos_arr[i] = np.cos(click_ang_fr * i)

sin_arr = np.empty(CHUNK, dtype = float)                         #to store values of sin
for i in range(CHUNK):
    sin_arr[i] = np.sin(click_ang_fr * i)

click = np.empty(CHUNK, dtype = np.int16)
click = np.cast[np.int16](sin_arr * 32767)                         #creating sine wave in click buffer

testclip = np.zeros([CLIPLENGTH, CHUNK], dtype = np.int16)          #stores data recorded during test

clicknesses = np.zeros([CLIPLENGTH], dtype = np.single)             #for storing RMS of click frequency component for each buffer in testclip

clickest_buffer = 0                                                 #for storing index of most click-like buffer

def clickness(buffer):                                              #calculates RMS (with resonant filter at click frequency) of a buffer
    #this function is supposed to return the summation of ((f(t)*sin(t))^2 + (f(t)*cos(t))^2)/2 over the input buffer
    return(((np.sum(np.multiply(buffer, sin_arr)))**2 + (np.sum(np.multiply(buffer, cos_arr)))**2)/2)

current_buffer = -1
#index for iteration through testclip within stream callback function.
#will be incremented before it is used

test_started = False

#following stream callback function, plays 1 buffer of click followed by CLIPLENGTH - 1 buffers of silence, and simultaneously records testclip.
def test_callback(in_data, frame_count, time_info, status):
    global clicknesses
    global click
    global testclip
    global current_buffer
    global tmp_buf

    if not test_started:
        return(silence, pyaudio.paContinue)

    current_buffer = current_buffer + 1

    if (current_buffer == CLIPLENGTH):
        return(silence, pyaudio.paComplete)

    testclip[current_buffer, :] = np.frombuffer(in_data, dtype = np.int16)    
    
    if (current_buffer == 0):
        return(click, pyaudio.paContinue)
    else:
        return(silence, pyaudio.paContinue)

test_stream = pa.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    output=True,
    input_device_index = INDEVICE,
    output_device_index = OUTDEVICE,
    frames_per_buffer = CHUNK,
    start = False,
    stream_callback = test_callback
)

print('Make sure any hardware monitoring is turned OFF and hold speaker and microphone close together.')

test_stream.start_stream()

input('When ready, press Enter.')

print('Testing...')

test_started = True
while(test_stream.is_active()):
    time.sleep(0.1)

print('Calculating latency...')

for i in range(CLIPLENGTH): #calculating clicknesses
    clicknesses[i] = clickness(testclip[i, :])
    print('Correlation of buffer ' + str(i) + ': ' +  str(clicknesses[i]))

for i in range(CLIPLENGTH): #finding index of clickest buffer
    if (clicknesses[i] > clicknesses[clickest_buffer]):
        clickest_buffer = i
print('Maximum correlation found at buffer ' + str(clickest_buffer) + ', therefore latency is ' + str(clickest_buffer) + ' buffers.\nNow testing statistical significance...')

mean_clickness = 0
for i in range(CLIPLENGTH): #calculating mean clickness of buffers in testclip
    mean_clickness = mean_clickness + clicknesses[i]
mean_clickness = mean_clickness / CLIPLENGTH
print('Average correlation = ' + str(mean_clickness))

standard_deviation = 0
for i in range(CLIPLENGTH): #calculating standard deviation in clickness of buffers in testclip
    standard_deviation = standard_deviation + (clicknesses[i] - mean_clickness)**2
standard_deviation = standard_deviation / CLIPLENGTH
standard_deviation = standard_deviation**(1/2)
print('Standard deviation = ' + str(standard_deviation))

confidence = abs(clicknesses[clickest_buffer] - mean_clickness) / standard_deviation

print('Confidence = ' + str(confidence) + ' standard deviations')

latency_in_milliseconds = int((clickest_buffer * CHUNK / RATE) * 1000)

if (confidence > 6): #test for statistical significance
    print('Measured latency is ' + str(clickest_buffer) + ' buffers with buffer size ' + str(CHUNK) + ' at sample rate ' + str(RATE / 1000) + 'kHz')
    print('i.e. about ' + str(latency_in_milliseconds) + ' milliseconds.')
    if (input('Set measured value as latency value for looping? (y/n): ') == 'y'):
        settings_file = open('Config/settings.prt', 'r')
        parameters = settings_file.readlines()
        settings_file.close()
        settings_file = open('Config/settings.prt', 'w')
        parameters[2] = str(latency_in_milliseconds) + '\n'
        for i in range(6):
            settings_file.write(parameters[i])
        settings_file.close()
        print('Done.')
else:
    print('Test not conclusive, please\na) Move mic and speaker closer together\nb) Turn up volume\nc) Move to a quieter location')

input('Press Enter')
