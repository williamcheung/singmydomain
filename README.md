**Sing My Domain** helps you decide on a domain name for your app before you pay for it — by letting you *experience* it first.

## What it does

You describe your app, get AI-suggested domain names, search availability, then before registering and spending money, you hear and see your chosen domain brought to life:

- A custom **jingle** sung to your domain name
- A **brand video** with a voiceover of the jingle lyrics
- A **spoken announcement** when your domain is registered

## How I used the MiniMax models

**MiniMax M3** (via GMI Cloud) powers two things: generating catchy jingle lyrics tailored to the domain name and app description, and suggesting creative domain name ideas from a keyword. M3's speed and low token usage made it ideal for these short, creative generation tasks where the user is waiting in real time.

**MiniMax Music 3.0** (via GMI Cloud) takes the M3-generated lyrics and composes a full jingle — vocals, melody, and instrumentation — in one API call. The result is a unique, brand-appropriate song the user can download and keep.

**MiniMax H3** (via GMI Cloud) generates an 8-second cinematic brand video from the jingle lyrics, with the chorus delivered as a voiceover. The user sees their domain name on screen in a visual context that matches the emotional tone of their app.

**MiniMax Speech 2.8** (via GMI Cloud) announces when the domain is successfully registered in a natural female voice, making the experience feel polished and responsive rather than silent. Due to GMI Cloud capacity constraints during the hackathon period, the app falls back to browser TTS when Speech 2.8 is unavailable, so the user always hears the announcement.

Together, the four models turn a dry domain registration flow into a creative brand experience that helps the user commit to their choice with confidence.
