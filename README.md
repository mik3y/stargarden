# Stargaden

Stargarden is a python program that runs the sound and lighting program for "Stargarden", an art installation.

Stargarden is a secluded spot in a nighttime forest, featuring a comfy platform for lying down, looking up at the stars, and taking in the atmosphere.

As a visitor approaches Stargarden, they see trees encircling the platform which are uplighted with various multi-color DMX fixtures, slowly and even subtly changing against a coherent color theme. Ambient background forest sounds play on sound system in the background, which encircles the space. Occasionally, a discrete sound (like a bird flapping or calling) is also played over the ambient selection, this sound taking advantage of the quad-channel sound output to make it appear to come from a specific space, or move around the space.

Unbeknownst to the visitor, upon their arrival, a bluetooth motion sensor has fired and determined that the space is occupied. After a set amount of time (e.g. 10 minutes), something happens: The lights fade off briefly, and a new sound takes over: a musical track from a privately curated playlist of chill, beautiful runes. The lighting program gets slightly more active and matches the music.

As the track ends, the "normal" program returns. So long as presence is detected in the space, the program repeats after another delay, with a new track.

## Design

### States

The program, and the art itself, has the following major states:
* `OFF`: All lighting and sound disabled.
* `AMBIENT`: Ambient forest sounds and lighting; the default mode of operation.
* `PRESENCE`: Ambient programming continues, but triggers the musical program after a timeout, looping back to this state so long as there is presence. The state transitions back to `AMBIENT` after the program determines the space has definitively been vacated.

## Major Components

* **Audio player.** This component is responsible for driving audio output. The program can be operating in stereo mode, or 4-channel "quadraphonic" mode, depending on the computer it is running on. The player has to mix/multiplex among a variety of streams (background ambience; occasional discrete sounds; music program), and is coordinated with lighting.
* **Lighting player.** This component drives a discrete set of DMX fixtures with pre-set colors, moods, patterns, themes. By default, it will run with a handful of RGB/RGBW wash lights attached. It may also be installed with one or more optional strobe-capable lights, supporting overlaying an occasional "lightning" effect, as called for by the program's lighting design.
* **Presence detection.** One or more BLE sensors (Shelly Blu Motion) will be connected and will provide simple motion detection events. This component aggregates these signals and implements latching and dampening; for example, presence being fired at the platform means someone is definitely there now, but their still motion could mean there is still someone present even if the sensor hasn't fired recently. At least one sensor is positioned on the walkway leading to the space, which could be incorporated in hueristics which determine overall logical presence/absence.
* **TUI console.** A console program makes it easy to see recent log messages, manually change state, and manually adjust the relative volume of each audio playback layer. (The overall peak volume will be set and managed by an external amplifier.)

## Requirements

* Written in Python.
* Can run on a developer device (MacBook) or the field-deployed "production" device (likely a Raspberry Pi running Raspberry Pi OS).
* In stereo mode, quadraphonic effects are simulated over 2 channels, e.g. so a developer can test their effectiveness.

## Open Questions

* How do we design the lighting program(s)? Do we use a third-party lighting desk program, or do we write all of the logic in Python (against fixture profiles we will need to source or design)?
* Do specific music tracks get associated with specific alternative lighting programs, or do we simply have a small playlist (possibly just 1) from which a lighting program is randomly chosen?
