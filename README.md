# raspi-looper
Simple 4 track looper for RaspBerry Pi. Uses pyaudio.

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

Demo in YouTube video.
