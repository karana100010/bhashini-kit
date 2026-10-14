// Framework-agnostic browser helpers for the Bhashini proxy (server/app.py).
// Works in plain HTML, React, Vue, Svelte, Angular... it is just an ES module.
//
//   import { createBhashini } from './bhashini.js';
//   const bhashini = createBhashini({ baseUrl: '' });   // '' = same origin as the proxy
//   const text = await bhashini.recordAndTranscribe('hi');       // mic -> text
//   await bhashini.speak('नमस्ते', 'hi');                          // text -> audio
//   const hi = await bhashini.translate('Hello', 'en', 'hi');     // text -> text
//   const wav = await fileToWav(file);                            // any audio file -> 16 kHz WAV base64
//
// The API key never reaches the browser; every call goes through your server.

// headers: extra request headers, or a function returning them (e.g. () => ({ 'X-Access-Code': code })).
export function createBhashini({ baseUrl = '', workletUrl = new URL('./pcm-worklet.js', import.meta.url).href, headers = {} } = {}) {
    let player = null;

    async function post(path, body, timeoutMs = 60000, method = 'POST') {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const url = path.startsWith('/') ? `${baseUrl}${path}` : `${baseUrl}/api/bhashini/${path}`;
            const response = await fetch(url, {
                method, headers: { 'Content-Type': 'application/json', ...(typeof headers === 'function' ? headers() : headers) },
                body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
            });
            const data = await response.json().catch(() => null);
            if (!response.ok) {
                const error = new Error(data?.error?.message || `Bhashini ${path} failed (${response.status}).`);
                error.status = response.status;
                throw error;
            }
            return data;
        } catch (error) {
            if (error.name === 'AbortError') throw new Error(`Bhashini ${path} timed out.`);
            throw error;
        } finally {
            clearTimeout(timer);
        }
    }

    /** Text -> text. */
    async function translate(text, source, target, { serviceId } = {}) {
        return (await post('translate', { text, source, target, service_id: serviceId })).text;
    }

    /** Base64 16 kHz mono WAV -> text. language may be 'auto'. */
    async function transcribe(wavBase64, language) {
        return (await transcribeDetailed(wavBase64, language)).text;
    }

    /** Same as transcribe, but returns {text, language, duration, segments, detected?}. Up to 10 minutes. */
    async function transcribeDetailed(wavBase64, language, { serviceId } = {}) {
        return post('asr', { audio_content: wavBase64, language, service_id: serviceId }, 600000);
    }

    /** Spoken language of a recording -> {language, score, candidates}. */
    const detectAudioLanguage = (wavBase64, { serviceId } = {}) =>
        post('detect-audio-language', { audio_content: wavBase64, service_id: serviceId });

    /** Speech in `source` -> {transcript, translation, audio?} in `target`. Max 45 s. */
    const speechTranslate = (wavBase64, source, target, { speak = false, gender, asrServiceId, nmtServiceId, ttsServiceId } = {}) =>
        post('speech-translate', { audio_content: wavBase64, source, target, speak, gender,
            asr_service_id: asrServiceId, nmt_service_id: nmtServiceId, tts_service_id: ttsServiceId }, 120000);

    /** Remove background noise -> {audio_content, mime_type}. Max 45 s. */
    const denoise = (wavBase64, { serviceId } = {}) => post('denoise', { audio_content: wavBase64, service_id: serviceId }, 90000);

    /** Same words in another script. sentence:false returns suggestions for one word. */
    const transliterate = (text, source, target, { sentence = true, suggestions = 5, serviceId } = {}) =>
        post('transliterate', { text, source, target, sentence, suggestions, service_id: serviceId });

    /** Language of a piece of text -> {language, script, score, candidates}. */
    const detectLanguage = (text, { serviceId } = {}) => post('detect-language', { text, service_id: serviceId });

    /** Named entities in Indic text -> {entities: [{text, tag, start, end}]}. */
    const entities = (text, language, { serviceId } = {}) => post('ner', { text, language, service_id: serviceId });

    /** Printed text in a PNG/JPEG -> {text}. Pass {imageBase64} or {imageUrl}. */
    const ocr = ({ imageBase64, imageUrl, language, serviceId }) =>
        post('ocr', { image_content: imageBase64, image_url: imageUrl, language, service_id: serviceId }, 120000);

    /** Selectable models per task: {models: {asr: [{id, provider, languages|source+target, ok}], ...}, defaults}. */
    const listModels = () => post('/api/models', undefined, 15000, 'GET');

    /** Saved transcripts (server-side, data/transcripts/). */
    const saveTranscript = ({ text, language, source = 'asr', title = '', audioBase64 } = {}) =>
        post('/api/transcripts', { text, language, source, title, audio_content: audioBase64 });
    const listTranscripts = async () => (await post('/api/transcripts', undefined, 30000, 'GET')).transcripts;
    const deleteTranscript = id => post(`/api/transcripts/${encodeURIComponent(id)}`, undefined, 30000, 'DELETE');

    /** Text -> spoken audio. Resolves when playback finishes; call stop() to cut it short. */
    async function speak(text, language, { gender, serviceId } = {}) {
        stop();
        const { segments } = await post('tts', { text, language, gender, service_id: serviceId }, 90000);
        const current = { stopped: false, audio: null };
        player = current;
        for (const segment of segments) {
            if (current.stopped) return;
            current.audio = new Audio(`data:${segment.mime_type};base64,${segment.audio_content}`);
            await new Promise((resolve, reject) => {
                current.audio.onended = resolve;
                current.audio.onpause = resolve;
                current.audio.onerror = () => reject(new Error('Audio playback failed.'));
                current.audio.play().catch(reject);
            });
        }
    }

    function stop() {
        if (!player) return;
        player.stopped = true;
        player.audio?.pause();
        player = null;
    }

    /**
     * Opens the microphone and returns a recorder. Must be called from a user
     * gesture (click/tap). Requires HTTPS or localhost.
     *   const rec = await bhashini.startRecording({ autoStop: true, onSpeech, onStop });
     *   const wavBase64 = await rec.stop();   // or wait for autoStop (end of speech)
     */
    async function startRecording({ autoStop = true, silenceMs = 1300, maxSeconds = 45, onSpeech } = {}) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
        const context = new AudioContext();
        await context.audioWorklet.addModule(workletUrl);
        const source = context.createMediaStreamSource(stream);
        const node = new AudioWorkletNode(context, 'bhashini-pcm-capture');
        const chunks = [];
        const vad = createVoiceActivityDetector(context.sampleRate, { silenceMs });
        let finish;
        const done = new Promise(resolve => { finish = resolve; });
        let spoke = false;
        let closed = false;

        const close = () => {
            if (closed) return;
            closed = true;
            node.port.onmessage = null;
            source.disconnect();
            node.disconnect();
            stream.getTracks().forEach(track => track.stop());
            context.close();
            try { finish(audioBase64(encodeWav(chunks, context.sampleRate))); } catch (error) { finish(Promise.reject(error)); }
        };

        node.port.onmessage = ({ data }) => {
            chunks.push(data);
            const state = vad.push(data);
            if (state.speech && !spoke) { spoke = true; onSpeech?.(); }
            const seconds = chunks.reduce((n, c) => n + c.length, 0) / context.sampleRate;
            if ((autoStop && (state.finished || state.empty)) || seconds >= maxSeconds) close();
        };
        source.connect(node);

        return { stop: () => { close(); return done; }, done };
    }

    /** One call: click -> listen until the user stops talking -> text. */
    async function recordAndTranscribe(language, options) {
        const recorder = await startRecording({ autoStop: true, ...options });
        return transcribe(await recorder.done, language);
    }

    return {
        translate, transcribe, transcribeDetailed, speak, stop, startRecording, recordAndTranscribe,
        detectAudioLanguage, speechTranslate, denoise, transliterate, detectLanguage, entities, ocr,
        saveTranscript, listTranscripts, deleteTranscript, listModels, post,
    };
}

// Energy-based end-of-speech detection. Tune threshold for noisy rooms.
export function createVoiceActivityDetector(sampleRate, { threshold = 0.015, minimumSpeechMs = 240, silenceMs = 1300, initialSilenceMs = 12000 } = {}) {
    let elapsed = 0, voiced = 0, silence = 0, detected = false;
    return {
        push(samples) {
            const duration = samples.length / sampleRate * 1000;
            elapsed += duration;
            const energy = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
            if (energy >= threshold) {
                voiced += duration;
                silence = 0;
                if (voiced >= minimumSpeechMs) detected = true;
            } else {
                silence += duration;
                if (!detected && silence > 300) voiced = 0;
            }
            return { speech: detected, finished: detected && silence >= silenceMs, empty: !detected && elapsed >= initialSilenceMs };
        },
    };
}

// Float32 chunks at the mic's native rate -> 16 kHz mono 16-bit WAV (what Bhashini ASR expects).
export function encodeWav(chunks, sourceRate, targetRate = 16000) {
    const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
    if (length < sourceRate / 4) throw new Error('Recording too short. Speak for at least a quarter second.');
    const samples = new Float32Array(length);
    let offset = 0;
    for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
    const count = Math.floor(length * targetRate / sourceRate);
    const buffer = new ArrayBuffer(44 + count * 2);
    const view = new DataView(buffer);
    const text = (at, value) => [...value].forEach((char, i) => view.setUint8(at + i, char.charCodeAt(0)));
    text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, count * 2, true);
    for (let i = 0; i < count; i++) {
        const start = Math.floor(i * sourceRate / targetRate);
        const end = Math.min(length, Math.max(start + 1, Math.floor((i + 1) * sourceRate / targetRate)));
        let sample = 0;
        for (let j = start; j < end; j++) sample += samples[j];
        sample = Math.max(-1, Math.min(1, sample / (end - start)));
        view.setInt16(44 + i * 2, Math.round(sample < 0 ? sample * 32768 : sample * 32767), true);
    }
    return new Uint8Array(buffer);
}

export function audioBase64(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
}

/** Any audio file or Blob the browser can decode (mp3, m4a, ogg, wav...) -> base64 16 kHz mono WAV. */
export async function fileToWav(file, targetRate = 16000) {
    const decoder = new AudioContext();
    let decoded;
    try {
        decoded = await decoder.decodeAudioData(await file.arrayBuffer());
    } catch {
        throw new Error('This file is not audio the browser can read.');
    } finally {
        decoder.close();
    }
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * targetRate), targetRate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return audioBase64(encodeWav([rendered.getChannelData(0)], targetRate, targetRate));
}

/** Base64 -> Blob, e.g. to offer a WAV download. */
export function base64Blob(base64, type = 'audio/wav') {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type });
}
