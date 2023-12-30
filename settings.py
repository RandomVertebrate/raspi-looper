f = open('Config/settings.prt', 'r')
parameters = f.readlines()
while (len(parameters) < 6):
    parameters.append('\n')
f.close()

parameters[0] = input('Enter Sample Rate in Hz (Safe Choices 44100 and 48000): ') + '\n'
parameters[1] = input('Enter Buffer Size (Typical 256, 512, 1024) : ') + '\n'
parameters[2] = '50\n' #input('Enter Latency Correction in milliseconds: ') + '\n'
parameters[3] = input('Enter Input Device Index (Probably 1 or 0) : ') + '\n'
parameters[4] = input('Enter Output Device Index (Probably Same as Input) : ') + '\n'
parameters[5] = input('Enter Margin for Late Button Press in Milliseconds (Around 500 seems to work well) : ') + '\n'

f = open('Config/settings.prt', 'w')
for i in range(6):
    f.write(parameters[i])
f.close()
