// Live ASR over a WebSocket to stream_app.py (which relays to Bhashini's socket.io stream).
//
//   const live = createLiveAsr({ url: 'ws://localhost:8766/ws/asr', language: 'hi', onPartial, onFinal });
//   await live.startMic();      // or: await live.streamFile(file)
//   await live.stop();          // resolves after the last final text
//
// Audio goes out as 16 kHz mono 16-bit PCM. A short pause (pauseMs) finalises the current
// utterance, so long sessions come back as a list of sentences instead of one growing string.

export function createLiveAsr({ url, language = 'hi', pauseMs = 900, threshold = 0.012, onReady, onPartial, onFinal, onError, onEnd } = {}) {
    const recorded = [];            // Int16Array chunks, kept so the session can be saved as WAV
    let socket = null, context = null, stream = null, node = null, source = null, ended = null;
    let silence = 0, voiced = false;

    function open() {
        return new Promise((resolve, reject) => {
            socket = new WebSocket(url);
            socket.binaryType = 'arraybuffer';
            let finish;
            ended = new Promise(r => { finish = r; });
            socket.onopen = () => socket.send(JSON.stringify({ type: 'start', language }));
            socket.onmessage = ({ data }) => {
                const message = JSON.parse(data);
                if (message.type === 'ready') { onReady?.(); resolve(); }
                else if (message.type === 'partial') onPartial?.(message.text);
                else if (message.type === 'final') onFinal?.(message.text);
                else if (message.type === 'error') { onError?.(message.message); reject(new Error(message.message)); }
                else if (message.type === 'end') finish();
            };
            socket.onerror = () => reject(new Error('Could not reach the streaming server.'));
            socket.onclose = () => { finish(); onEnd?.(); };
        });
    }

    // Resample Float32 at `rate` to 16 kHz Int16, keeping the fractional position between chunks.
    let carry = 0;
    function toPcm16(samples, rate) {
        const step = rate / 16000, out = [];
        let position = carry;
        while (position < samples.length) {
            const start = Math.floor(position), end = Math.min(samples.length, Math.max(start + 1, Math.floor(position + step)));
            let sum = 0;
            for (let i = start; i < end; i++) sum += samples[i];
            const v = Math.max(-1, Math.min(1, sum / (end - start)));
            out.push(v < 0 ? v * 32768 : v * 32767);
            position += step;
        }
        carry = position - samples.length;
        return Int16Array.from(out);
    }

    function send(samples, rate) {
        if (socket?.readyState !== WebSocket.OPEN) return;
        const pcm = toPcm16(samples, rate);
        recorded.push(pcm);
        socket.send(pcm.buffer);
        // Pause detection: finalise the utterance after `pauseMs` of quiet following speech.
        const energy = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
        if (energy >= threshold) { voiced = true; silence = 0; }
        else if (voiced && (silence += samples.length / rate * 1000) >= pauseMs) {
            socket.send(JSON.stringify({ type: 'flush' }));
            voiced = false;
            silence = 0;
        }
    }

    async function startMic({ workletUrl = '/pcm-worklet.js' } = {}) {
        await open();
        stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
        context = new AudioContext();
        await context.audioWorklet.addModule(workletUrl);
        source = context.createMediaStreamSource(stream);
        node = new AudioWorkletNode(context, 'bhashini-pcm-capture');
        node.port.onmessage = ({ data }) => send(data, context.sampleRate);
        source.connect(node);
    }

    /** Plays a file into the stream at real-time speed (handy for testing without a mic). */
    async function streamFile(file, { speed = 1 } = {}) {
        const decoder = new AudioContext();
        const buffer = await decoder.decodeAudioData(await file.arrayBuffer()).finally(() => decoder.close());
        await open();
        const samples = buffer.getChannelData(0), rate = buffer.sampleRate, chunk = Math.round(rate / 10);
        const started = performance.now();
        for (let i = 0; i < samples.length && socket?.readyState === WebSocket.OPEN; i += chunk) {
            send(samples.subarray(i, i + chunk), rate);
            // Pace by the clock, not per-chunk sleeps, so throttled background-tab timers catch up.
            const due = started + (i + chunk) / rate * 1000 / speed - performance.now();
            if (due > 0) await new Promise(r => setTimeout(r, due));
        }
    }

    async function stop() {
        node && (node.port.onmessage = null);
        source?.disconnect();
        stream?.getTracks().forEach(t => t.stop());
        await context?.close();
        node = source = stream = context = null;
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'stop' }));
        await ended;
    }

    /** Everything sent so far as base64 16 kHz WAV, or null. */
    function recordingWav() {
        const count = recorded.reduce((n, c) => n + c.length, 0);
        if (!count) return null;
        const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
        const text = (at, value) => [...value].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
        text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
        view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        text(36, 'data'); view.setUint32(40, count * 2, true);
        let offset = 44;
        for (const chunk of recorded) { new Int16Array(buffer, offset, chunk.length).set(chunk); offset += chunk.length * 2; }
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        return btoa(binary);
    }

    return { startMic, streamFile, stop, recordingWav };
}
