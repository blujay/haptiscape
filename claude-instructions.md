# Working with Claude on Haptiscape
### A Prompt Guide for Artists, Engineers & Collaborators

This guide is for anyone working on this project — whether you're the original artist-engineer, a student picking it up for the first time, or a collaborator exploring it from a different angle. It's about how to get the most out of Claude as a technical partner, not just a code generator.

Claude works best here when treated as a curious engineering collaborator who can hold the context of the whole system, respond to ambiguity without needing everything resolved upfront, and follow the artistic intent of the work — not just the technical spec.

---

## What this project is

Haptiscape is a wearable haptic feedback system running on a Raspberry Pi Pico W. It listens to audio in real time from a variety of input sources (see section) and translates it into vibration patterns vibrating motors (LRA & ERM) motors, creating a physical sensation that mirrors what's being heard. The cello variant (`cello_haptic.py`) is designed for performance use — worn on the back, feeling the instrument from the inside.

### The codebase spans:
- **`cello_haptic.py`** — standalone cello-specific haptic engine with full diagnostics
- **`haptic_engine.py`** — generic version for any audio source (voice, music, breath)
- **`main.py`** — web-served system with Wi-Fi, UI, SD playback, and mode switching
- **`main_mic.py`** — mic DSP engine with adaptive noise floor
- **`main_sd.py`** — WAV file player with envelope-driven haptics
- **`mode_manager.py`** — state machine for switching between input modes
- **`interface.py`** — mobile web UI served from the Pico itself
- **`config.py` / `secrets.py`** — hardware pin assignments and Wi-Fi credentials

---

### Input modes
- **'Live mic audio'** - plays directly from a single or double mic for stereo effect. 
- **'Stored audio'** - plays from a wav file stored on the onboard SD card. 
- **'Unity timeline signal'** - plays from a set of stored wavs or patterns triggered by Unity 
- **'Live data stream'** - plays from an interpretation of a data stream
- **'Stored data'** - plays from a stored data source such as a spreadsheet or json file
- **'Live Unity spatial'** - plays from a live spatial sound output 'headset listener'
- **'Pattern library'** - plays from a selected haptic pulse pattern library
- **'Generative audio'** - converts visual data into generative audio via camera feed

## The collaboration model

Think of Claude as an engineer who has read all the code and is sitting next to you in the studio. You don't have to re-explain the project each time, but you do need to say enough that Claude knows which part you're working on and what you're trying.

You're the artist and lead engineer. Claude responds to artistic intent as well as technical requirements. Saying "I want it to feel more like breathing and less like a metronome" is a valid instruction.

---

## How to start a session

Always open with a brief context anchor. This doesn't need to be long — three things are enough:

1. **What you're working on** — which file or subsystem
2. **What state it's in** — does it work? is it broken? is it a new idea?
3. **What you want** — explore, fix, build, explain, or rethink

**Example:**
```
I'm working on haptic_engine.py — the adaptive noise floor tracker. It's working but 
in a loud room it gates out too aggressively and the haptics drop completely for half 
a second. I want to explore whether a slower gate release would help, or if there's 
a different approach. Not looking for a final solution yet, just want to understand 
the tradeoff.
```

This is better than "fix my noise gate" because it tells Claude what you already know, what you've observed, and that you're in exploration mode — not execution mode.

---

## Keeping context across a session

Claude doesn't remember previous conversations. Within a session, it does. A few habits help:

**State the constraints once, early.** If something must not change (e.g. "the PWM frequency must stay at 200Hz for the ERM motors", or "we can't use floats here because of memory"), say it once at the top of the conversation. Claude will hold it.

**Name the file you're in.** `haptic_engine.py` and `main_mic.py` have similar-sounding functions. Being explicit avoids confusion.

**When switching focus, say so.** "Let's leave the noise floor for now and look at the SD playback in `main_sd.py`" resets the context cleanly.

**Paste the relevant code block.** If you've made changes since the session started, paste the current version. Claude's reference is the version it last saw.

---

## Types of request — and how to phrase them

### Explore / experiment

Use this when you're not sure what you want yet. Claude is good at laying out options without committing to one.

```
I'm thinking about adding a third haptic zone — maybe a motor at the shoulder 
to represent bow position separately from volume. I don't know if this is 
physically practical or musically meaningful. Can you help me think through 
what data we'd use to drive it and what the feel might be?
```

Claude will explore the idea with you, flag the practical constraints (GPIO availability, power draw, added latency), and suggest approaches without assuming you've decided anything.

### Fix something specific

Be precise about the symptom, not just the goal.

```
In main_mic.py, the HapticMicEngine sometimes stops responding after about 
10 minutes of use. The motors go silent and don't recover until reset. 
I think it might be related to the adaptive bias drifting but I'm not sure. 
Can you look at the process() method and tell me what might cause a silent 
failure like this?
```

Describing the symptom ("stops responding after 10 minutes") is more useful than the goal ("make it more reliable") because it gives Claude something to trace.

### Build something new

When you know what you want, describe the behaviour and the constraints together.

```
I want to add a "pulse mode" to the mic engine — when the audio is very steady 
(low variance, sustained note), the haptics should gently pulse at around 1Hz 
rather than holding steady. When the audio is dynamic (bow changes, vibrato), 
it goes back to continuous. Keep it within the existing HapticMicEngine class. 
MicroPython only — no external libraries.
```

The key ingredients: what it does, when it activates, what it reverts to, and any hard constraints.

### Explain how something works

Useful when you're picking up someone else's code or returning after a break.

```
Can you walk me through how the zero-crossing rate calculation in haptic_engine.py 
works, and why it's being used as a spectral proxy? I want to understand the 
tradeoff vs doing a lightweight FFT.
```

Claude will explain the logic, the tradeoff, and the alternatives — without assuming you need a full DSP lecture.

### Rethink the architecture

Use this when something feels wrong at a higher level.

```
The mode_manager.py is getting complicated. I'm now handling mic_enable, 
mic_disable, mic_toggle, mic_sens_up, mic_sens_down as separate modes, and 
it feels like mode strings were the wrong abstraction for settings changes. 
Can you help me think about whether these should be commands rather than modes, 
and what that refactor would look like?
```

Claude can step back from the code and think about the design.

---

## Hardware-specific context worth including

When working on hardware behaviour, these details help Claude give accurate responses:

- **Pico W** — dual-core RP2040, MicroPython, no hardware float unit, 264KB RAM
- **ERM motors** — respond to PWM duty cycle (intensity), not audio frequency directly. 50–300Hz envelope response. Carrier at 200Hz.
- **ADC** — 12-bit native (0–4095), reads as 16-bit scaled (0–65535) in MicroPython. There's noise on the ADC reference — a flat-line reading often means wiring, not silence.
- **PWM** — 16-bit duty (0–65535). `machine.PWM` freq and duty set independently.
- **Wi-Fi** — STA mode preferred. AP fallback available but slower. The Pico W can only connect to 2.4GHz networks.
- **SD card** — SPI bus, FAT filesystem, mounted at `/sd`. WAV files only. Stereo 16-bit at 44.1kHz works fine; higher sample rates may stutter.

If Claude suggests something that doesn't fit these constraints, push back and it will adapt.

---

## Artistic direction and non-technical intent

This system is for a performer. The haptic output should feel expressive, not mechanical. Some useful framings:

**Talk about feel, not just values.** "The release feels too snappy — it cuts off rather than fading" is as valid as "reduce RELEASE_COEFF." Claude can translate between them.

**Reference the performance context.** "During a long sustained note the buzz gets fatiguing" is useful. Claude will think about performer experience, not just signal accuracy.

**Ambiguity is fine.** "I'm not sure if the stereo panning is actually adding anything" is a good prompt. Claude can help you think it through rather than waiting for a decision.

**You can reject suggestions.** Claude will propose things. If the direction is wrong — too clean, too literal, wrong vibe — say so. "That's too algorithmic, I want something that feels more organic and unpredictable" is a complete instruction.

---

## Snippets and experiments

When Claude produces code, it's a starting point, not a final answer. Some ways to work iteratively:

**Ask for a diff, not a full rewrite.** "Show me just the changes to the `process()` method" keeps things legible when you're mid-session.

**Ask for two versions.** "Give me a conservative version and a more experimental version" lets you compare approaches before committing.

**Ask for comments on tradeoffs.** "What am I giving up with this approach?" is always a valid follow-up.

**Ask what to test first.** "If I flash this, what should I check before playing with it live?" helps you validate in a sensible order.

---

## Things to avoid

**Don't start a session with just a code block.** Claude will try to respond but won't know what you want from it — a review, a fix, an explanation, or something else entirely.

**Don't ask for everything at once.** "Rewrite the whole haptic engine to be better" will produce something generic. Narrow the scope.

**Don't assume Claude knows which version you're on.** If you've made changes, share them. The project files shown are a snapshot — Claude doesn't see live edits.

**Don't ask Claude to decide the artistic direction.** It can offer options, lay out tradeoffs, and respond to your direction. But what the piece should feel like is yours to decide.

---

## Example opening prompts

**Starting fresh on a feature:**
```
I'm in main_sd.py working on the SDPlayerSession. I want to add support for 
looping — when a track finishes, it should restart from the beginning. Currently 
it just returns 'done' and goes idle. What's the simplest way to add a loop flag?
```

**Returning after a break:**
```
I've been away from this for a few weeks. Can you give me a quick summary of 
what haptic_engine.py does differently from main_mic.py, particularly around 
the noise floor? I want to understand which one I should be developing on.
```

**Exploring a creative idea:**
```
I'm performing with this next month. I've been thinking about whether the two 
motors should sometimes move independently rather than always panning together. 
Like — left motor for bow pressure, right motor for bow position (near bridge 
vs sul tasto). Is that architecturally feasible with the current ZCR approach 
or would I need a different input signal?
```

**Debugging on the day:**
```
Quick one — I'm about to go on stage in 2 hours and the right motor isn't 
responding. The left one works fine. The diagnostics in cello_haptic.py 
show both motors ramping during startup. What should I check first?
```

---

*This guide was written for Haptiscape. Adapt it as the project evolves.*