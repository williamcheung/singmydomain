async (text) => {
    console.log('text: ' + text);
    if (!text) {
        return;
    }

    // ensure voices are loaded
    const voices = await new Promise((resolve) => {
        if (window.speechSynthesis.getVoices().length !== 0) {
            resolve(window.speechSynthesis.getVoices());
        } else {
            window.speechSynthesis.onvoiceschanged = () => {
                resolve(window.speechSynthesis.getVoices());
            };
        }
    });

    const femaleNames = [
        // Windows
        'ava', 'emma', 'aria', 'jenny', 'michelle', 'ana',
        'zira', 'linda', 'susan', 'hazel', 'natasha', 'clara', 'emily',
        'molly', 'sonia', 'libby', 'maisie', 'leah', 'rosa', 'luna',
        // macOS
        'samantha', 'karen', 'moira', 'tessa', 'fiona', 'victoria'
    ];

    const femaleVoice =
        voices.find(voice =>
            voice.name.toLowerCase().includes('female') ||
            voice.name.toLowerCase().includes('woman')
        ) ||
        voices.find(voice => voice.lang === 'en-GB' && voice.name.toLowerCase().includes('online') &&
            femaleNames.some(name => voice.name.toLowerCase().split(/\W+/).includes(name))) ||
        voices.find(voice => voice.lang.startsWith('en') &&
            femaleNames.some(name => voice.name.toLowerCase().split(/\W+/).includes(name))) ||
        null;
    if (!femaleVoice) {
        console.log('No recognized female voice found; using default voice.');
    }

    let chunks = [text];

    // Google Chrome needs chunking, so check what browser
    const userAgent = navigator.userAgent;
    const vendor = navigator.vendor;
    console.log('userAgent: ' + userAgent);
    console.log('vendor: ' + vendor);
    if (/Google/.test(vendor) && /Chrome/.test(userAgent) && !/Edg/.test(userAgent)) {
        chunks = text.split('.').map(sentence => sentence.trim()).filter(sentence => sentence.length > 0);
    }

    for (let i = 0; i < chunks.length; i++) {
        await new Promise((resolve, reject) => {
            console.log('chunk: ' + chunks[i]);
            const utterance = new SpeechSynthesisUtterance(chunks[i]);
            // Set the voice if a female voice is found (else use default voice)
            if (femaleVoice) {
                utterance.voice = femaleVoice;
            }
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(utterance);

            utterance.onend = () => {
                resolve();
            };
            utterance.onerror = (error) => {
                resolve();
            };
        });
    }
}
