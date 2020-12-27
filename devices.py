import pyaudio

pa = pyaudio.PyAudio()
n = pa.get_device_count()

print('Found ' + str(n) + ' devices.')

for i in range(n):
    print('INDEX ' + str(i) + ': ' + str(pa.get_device_info_by_index(i)['name']))

pa.terminate()
