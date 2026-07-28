# Pico2-Synth
A Raspberry Pi Pico/Pico2 micropython code to make a MIDI controlled synthesizer with a MIDI to UART optocoupler circuit and a PCM5102a module sound card. Works with Pico 1, but the overclocking at 300_000_000 MHz might need be reduced and consequently also reduce FS (sampling rate)

The synthesizer is a monosynth, outputs only one note at a time with a selection of sine, square and sawtooth waves. Its filter is a biquad filter, with the cutoff adjustable with a MIDI CC 75 and the resonance Q is adjustable with MIDI CC 76. It has an AR envelopped (attack-release), with the attack and release parameters being hardcoded for now.

# Circuit
I have used the following ingredient for the MIDI to UART:
- MIDI connector 5 DIN
- 6N137 optocoupler IC
- 220 ohms resistor for the optocoupler internal LED current limiting.
- A schottky diode (optional) to protect the optocoupler from reversed polarity of the MIDI connector, between the pins of the optocoupler's internal LED.
- A 4.7kOhm resistor to pull down 3.3v into GPIO 17 of the Pi Pico

Then for the PCM5102 sound card, I first initialized the bridge solder pads as follows:
- SCK to ground (solder pads are on top)
- H1L to L
- H2L to L
- H3L to H
- H4L to L

The PCM5102 is hooked up to the Pico as follows:
- BCK is plugged into GPIO 26
- LCK is plugged into GPIO 27
- DIN is plugged into GPIO 28
- GND is plugged into analog ground of the Pico, the ground around pin 26,27,28
- VIN is plugged into 3.3V of the Pico

The optocoupler vo pin is sink for 3.3V of the Pico through a 4.7k resistor, and plugged into GPIO 17

Optionally a push button can be added to change the synthesizer waveform between sine, square, saw. The push button should be connected between ground and GPIO 15 on the Pico.

Here is what the optocoupler circuit should look like except now I used 4.7kohm instead of 10k and I used GPIO 17 instead of GPIO 1 on the PICO.
![optocoupler circuit](https://github.com/paul-caron/pico2-synth/blob/main/optocoupler.jpg?raw=true)
