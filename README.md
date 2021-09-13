# raspi-looper
Simple 4 track looper for Raspberry Pi. Uses pyaudio.

Uses a USB soundcard probably.
Uses 8 buttons (push-to-connect) and 8 LEDs to trigger and indicate playback and recording on 4 tracks.
One leg of each button goes to ground, as does the negative side of each LED.
The free legs of the buttons are connected as in gpio_connections.txt
The positive side of the LEDs are connected through 100Ohm current-limiting resistors to gpio pins as in gpio_connections.txt

Instructions (Setup):
Run devices.py first to check device index of your soundcard. Probably 1.
Run settings.py which edits Config/settings.prt
You can run latency.py to measure your round trip latency and update the value.
Run main.py to loop. You can add it to your .bashrc to run on boot.
May be a good idea to tweak ALSA and Pulse audio configuration files as needed.

Buttons' Functions:

    Press 'record' button: Start waiting to record/overdub, stop recording/overdubbing.
    Hold 'record' button: Clear track.
    Press 'play' button: Mute/Unmute track.
    Hold 'play' on track 1: Quit and start new looping session.
    Hold 'play' on track 4: Quit but don't restart (useful for making changes to your Raspberry Pi)

Demo in YouTube video: [Demo Video](https://youtu.be/0FDovuCira8)

## Installation Instructions
(assumes a fresh install of Raspberry Pi OS)

1. Clone this repository:
    ```git clone https://github.com/RandomVertebrate/raspi-looper```

2. Install Python3-PyAudio:
    ```sudo apt install python3-pyaudio```

3. Check your volume settings in AlsaMixer (F6 changes device):
    ```alsamixer``` (press escape to exit)

4. Change to the raspi-looper directory:
    ```cd raspi-looper```

5. Make a note of your audio device numbers:
    ```python3 devices.py```

6. Configure Raspi-Looper settings:
    ```python3 settings.py```
    (Set latency to 100ms for now and use the device numbers from above)

7. Find your latency:
    ```python3 latency.py```

8. Comment out the load-module module-suspend-on-idle in default.pa (ctrl-x then y to save and exit):
    ```sudo nano /etc/pulse/default.pa```

9. Configure auto-boot into Raspi-Looper (ctrl-x then y to save and exit):
    ```sudo nano /home/pi/.bashrc```
    Add the following lines at the end of the file:
    >cd /home/pi/raspi-looper
    
    >sudo python3 main.py
