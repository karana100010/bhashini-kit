// Demo UI for every service in the kit. Uses only the public bhashini.js API.
import { createBhashini, fileToWav, base64Blob } from './bhashini.js';

const ACCESS_KEY = 'bhashini-access-code';
const storage = {
    get: () => { try { return localStorage.getItem(ACCESS_KEY) || ''; } catch { return ''; } },
    set: v => { try { v ? localStorage.setItem(ACCESS_KEY, v) : localStorage.removeItem(ACCESS_KEY); } catch {} },
};
let accessCode = storage.get();
const bhashini = createBhashini({ headers: () => (accessCode ? { 'X-Access-Code': accessCode } : {}) });
const $ = id => document.getElementById(id);

const LANGUAGES = {
    hi: 'Hindi', en: 'English', bn: 'Bengali', ta: 'Tamil', te: 'Telugu', mr: 'Marathi', gu: 'Gujarati',
    kn: 'Kannada', ml: 'Malayalam', pa: 'Punjabi', or: 'Odia', as: 'Assamese', ur: 'Urdu', ne: 'Nepali',
    sa: 'Sanskrit', bho: 'Bhojpuri', mai: 'Maithili', doi: 'Dogri', kok: 'Konkani', ks: 'Kashmiri',
    sd: 'Sindhi', brx: 'Bodo', mni: 'Manipuri', sat: 'Santali', mag: 'Magahi', hne: 'Chhattisgarhi', raj: 'Rajasthani',
};
const langName = code => LANGUAGES[code] ? `${LANGUAGES[code]} (${code})` : code;

// --- status + busy helpers -----------------------------------------------------------------
function status(text, error = false) {
    $('status').textContent = text;
    $('status').classList.toggle('error', error);
}
async function run(button, label, fn) {
    button.disabled = true;
    status(label);
    try { status((await fn()) || ''); } catch (error) {
        status(`⚠ ${error.message}`, true);
        if (error.status === 401) askAccessCode();
    }
    finally { button.disabled = false; }
}
function download(blob, name) {
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const dataUrl = ({ audio_content, mime_type }) => `data:${mime_type};base64,${audio_content}`;

// --- tabs ------------------------------------------------------------------------------------
function showTab(name) {
    document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('section[data-panel]').forEach(s => s.classList.toggle('active', s.dataset.panel === name));
    status('');
    if (name === 'saved') loadSaved();
    if (name === 'settings') loadSettings();
    history.replaceState(null, '', `#${name}`);
}
document.querySelectorAll('#tabs button').forEach(b => { b.onclick = () => showTab(b.dataset.tab); });

// --- language selects ----------------------------------------------------------------------
document.querySelectorAll('select[data-langs]').forEach(select => {
    const exclude = (select.dataset.exclude || '').split(',');
    if (select.dataset.langs === 'auto') select.add(new Option('Auto-detect', 'auto'));
    for (const [code] of Object.entries(LANGUAGES)) if (!exclude.includes(code)) select.add(new Option(langName(code), code));
    select.value = select.dataset.default || 'hi';
});

// --- model menus: <select data-model="task" data-src="langSelectId" data-tgt="langSelectId"> --------
const TASK_NAMES = {
    asr: 'Speech → text', translation: 'Translation', transliteration: 'Transliteration', tts: 'Text → speech',
    'audio-lang-detection': 'Audio language detection', 'txt-lang-detection': 'Text language detection',
    ner: 'Names & places', ocr: 'OCR', denoiser: 'Denoiser',
};
let catalog = { models: {}, defaults: {} };
const shortId = id => id.replace(/^bhashini\//i, '');
const fits = (m, src, tgt) => m.source
    ? (!src || m.source.includes(src)) && (!tgt || m.target.includes(tgt))
    : !src || src === 'auto' || !m.languages.length || m.languages.includes(src);

function fillModelMenu(select) {
    const task = select.dataset.model, previous = select.value;
    const src = select.dataset.src && $(select.dataset.src).value, tgt = select.dataset.tgt && $(select.dataset.tgt).value;
    const models = (catalog.models[task] || []).filter(m => fits(m, src, tgt));
    const fallback = catalog.defaults[task];
    const label = m => `${m.ok ? '' : '⚠ '}${m.provider} · ${shortId(m.id)}${m.note ? ` (${m.note})` : ''}`;
    select.replaceChildren(new Option(fallback && models.some(m => m.id === fallback) ? `Default (${shortId(fallback)})` : 'Default (best available)', ''),
        ...models.map(m => new Option(label(m), m.id)));
    select.value = models.some(m => m.id === previous) ? previous : '';
    select.title = models.length ? `${models.length} model(s) for this language` : 'No listed model supports this language; Bhashini will try its default.';
}
const model = id => $(id).value || undefined;

async function loadModels() {
    try { catalog = await bhashini.listModels(); } catch { return; }
    fillDatalists();
    document.querySelectorAll('select[data-model]').forEach(select => {
        fillModelMenu(select);
        for (const key of ['src', 'tgt']) if (select.dataset[key]) $(select.dataset[key]).addEventListener('change', () => fillModelMenu(select));
    });
    const langs = m => (m.source ? `${m.source.join(' ')} → ${m.target.join(' ')}` : m.languages.join(' ')) || 'any';
    $('modelsTable').tBodies[0].replaceChildren(...Object.entries(catalog.models).flatMap(([task, list]) => list.map(m => {
        const row = document.createElement('tr');
        row.className = m.ok ? '' : 'down';
        for (const text of [TASK_NAMES[task] || task, null, `${m.provider}${m.note ? ` · ${m.note}` : ''}`, langs(m)]) {
            const cell = row.insertCell();
            if (text === null) cell.append(Object.assign(document.createElement('code'), { textContent: `${m.ok ? '' : '⚠ '}${m.id}` }));
            else cell.textContent = text;
        }
        row.cells[3].className = 'langs';
        return row;
    })));
}

// --- reusable audio input: record (auto-stops on silence) or upload --------------------------
function audioInput(container) {
    const state = { wav: null };
    container.innerHTML = `
        <button type="button" data-rec>🎤 Record</button>
        <label class="file">📁 Upload audio <input type="file" accept="audio/*,video/mp4"></label>
        <audio controls class="hidden"></audio>
        <span class="meta" data-info>No audio yet</span>`;
    const recButton = container.querySelector('[data-rec]');
    const player = container.querySelector('audio');
    const info = container.querySelector('[data-info]');
    let recorder = null;

    function set(wav, label) {
        state.wav = wav;
        player.src = `data:audio/wav;base64,${wav}`;
        player.classList.remove('hidden');
        info.textContent = label;
    }
    recButton.onclick = async () => {
        if (recorder) { recorder.stop(); return; }
        try {
            recorder = await bhashini.startRecording({ autoStop: false, maxSeconds: 600 });
            recButton.textContent = '⏹ Stop recording';
            recButton.classList.add('recording');
            info.textContent = 'Recording… press Stop when done';
            const wav = await recorder.done;
            set(wav, `Recorded ${(atob(wav).length / 32000).toFixed(1)} s`);
        } catch (error) {
            status(`⚠ ${error.message}`, true);
        } finally {
            recorder = null;
            recButton.textContent = '🎤 Record';
            recButton.classList.remove('recording');
        }
    };
    container.querySelector('input[type=file]').onchange = async event => {
        const file = event.target.files[0];
        if (!file) return;
        info.textContent = 'Converting…';
        try { set(await fileToWav(file), file.name); } catch (error) { info.textContent = error.message; }
        event.target.value = '';
    };
    state.require = () => {
        if (!state.wav) throw new Error('Record or upload some audio first.');
        return state.wav;
    };
    return state;
}

// --- Speech -> Text --------------------------------------------------------------------------
const asrAudio = audioInput($('asrAudio'));
let lastAsr = null;
$('asrRun').onclick = () => run($('asrRun'), 'Transcribing… long recordings take a while.', async () => {
    const result = await bhashini.transcribeDetailed(asrAudio.require(), $('asrLang').value, { serviceId: model('asrModel') });
    lastAsr = result;
    $('asrText').value = result.text;
    const detected = result.detected ? ` · detected ${langName(result.detected.language)}` : '';
    $('asrMeta').textContent = `${langName(result.language)} · ${result.duration} s · ${result.segments.length} segment(s)${detected}`;
});
$('asrSave').onclick = () => run($('asrSave'), 'Saving…', async () => {
    const text = $('asrText').value.trim();
    if (!text) throw new Error('Nothing to save yet. Transcribe first, or type the text.');
    const entry = await bhashini.saveTranscript({
        text, language: lastAsr?.language || $('asrLang').value, title: $('asrTitle').value,
        audioBase64: $('asrKeepAudio').checked ? asrAudio.wav : undefined,
    });
    return `✓ Saved as ${entry.id}. See “Saved transcripts”.`;
});
$('asrDownload').onclick = () => {
    const name = ($('asrTitle').value.trim() || 'transcript').replace(/[^\p{L}\p{N}_ -]+/gu, '_');
    download(new Blob([$('asrText').value], { type: 'text/plain;charset=utf-8' }), `${name}.txt`);
};
$('asrCopy').onclick = () => run($('asrCopy'), 'Copying…', async () => { await navigator.clipboard.writeText($('asrText').value); return 'Copied.'; });

// --- Text -> Speech --------------------------------------------------------------------------
$('ttsRun').onclick = () => run($('ttsRun'), 'Generating speech…', async () => {
    const text = $('ttsText').value, language = $('ttsLang').value, gender = $('ttsGender').value;
    const { segments } = await bhashini.post('tts', { text, language, gender, service_id: model('ttsModel') }, 90000);
    $('ttsDownload').href = URL.createObjectURL(base64Blob(segments[0].audio_content, segments[0].mime_type));
    $('ttsDownload').classList.remove('hidden');
    status('Playing…');
    for (const segment of segments) {
        const audio = new Audio(dataUrl(segment));
        ttsPlaying = audio;
        await new Promise((resolve, reject) => { audio.onended = audio.onpause = resolve; audio.onerror = reject; audio.play().catch(reject); });
    }
});
let ttsPlaying = null;
$('ttsStop').onclick = () => { ttsPlaying?.pause(); bhashini.stop(); };

// --- Voice translate -------------------------------------------------------------------------
const voiceAudio = audioInput($('voiceAudio'));
$('voiceRun').onclick = () => run($('voiceRun'), 'Recognising, translating, speaking…', async () => {
    const result = await bhashini.speechTranslate(voiceAudio.require(), $('voiceSrc').value, $('voiceTgt').value,
        { speak: $('voiceSpeak').checked, asrServiceId: model('voiceAsrModel'), nmtServiceId: model('voiceNmtModel'), ttsServiceId: model('voiceTtsModel') });
    $('voiceHeard').textContent = result.transcript;
    $('voiceOut').textContent = result.translation;
    $('voicePlayer').classList.toggle('hidden', !result.audio);
    if (result.audio) { $('voicePlayer').src = dataUrl(result.audio); $('voicePlayer').play().catch(() => {}); }
});

// --- Denoise ---------------------------------------------------------------------------------
const denoiseAudio = audioInput($('denoiseAudio'));
$('denoiseRun').onclick = () => run($('denoiseRun'), 'Removing noise…', async () => {
    const result = await bhashini.denoise(denoiseAudio.require());
    $('denoisePlayer').src = dataUrl(result);
    $('denoiseDownload').href = URL.createObjectURL(base64Blob(result.audio_content, result.mime_type));
    $('denoiseDownload').classList.remove('hidden');
});

// --- Translate -------------------------------------------------------------------------------
$('trSwap').onclick = () => { [$('trSrc').value, $('trTgt').value] = [$('trTgt').value, $('trSrc').value]; };
$('trRun').onclick = () => run($('trRun'), 'Translating…', async () => {
    $('trOut').textContent = await bhashini.translate($('trIn').value, $('trSrc').value, $('trTgt').value, { serviceId: model('trModel') });
});
$('trSpeak').onclick = () => run($('trSpeak'), 'Speaking…', async () => {
    if (!$('trOut').textContent.trim()) throw new Error('Translate something first.');
    await bhashini.speak($('trOut').textContent, $('trTgt').value);
});

// --- Transliterate ---------------------------------------------------------------------------
$('xlRun').onclick = () => run($('xlRun'), 'Transliterating…', async () => {
    const result = await bhashini.transliterate($('xlIn').value, $('xlSrc').value, $('xlTgt').value, { serviceId: model('xlModel') });
    $('xlOut').textContent = result.text;
    $('xlSuggest').innerHTML = '';
});
$('xlWord').onclick = () => run($('xlWord'), 'Getting suggestions…', async () => {
    const words = $('xlIn').value.trim().split(/\s+/);
    const result = await bhashini.transliterate(words.at(-1), $('xlSrc').value, $('xlTgt').value, { sentence: false, suggestions: 6, serviceId: model('xlModel') });
    $('xlSuggest').replaceChildren(...result.suggestions.map(word => {
        const chip = Object.assign(document.createElement('button'), { textContent: word, title: 'Use this word' });
        chip.onclick = () => { words[words.length - 1] = word; $('xlIn').value = words.join(' '); };
        return chip;
    }));
});

// --- Detect language -------------------------------------------------------------------------
const formatScore = s => (typeof s === 'number' ? ` · confidence ${Math.min(100, s * 100).toFixed(0)}%` : '');
$('tldRun').onclick = () => run($('tldRun'), 'Detecting…', async () => {
    const r = await bhashini.detectLanguage($('tldIn').value, { serviceId: model('tldModel') });
    $('tldOut').textContent = `${langName(r.language)} · script ${r.script}${formatScore(r.score)}`;
});
const aldAudio = audioInput($('aldAudio'));
$('aldRun').onclick = () => run($('aldRun'), 'Listening for the language…', async () => {
    const r = await bhashini.detectAudioLanguage(aldAudio.require(), { serviceId: model('aldModel') });
    $('aldOut').textContent = `${langName(r.language)}${formatScore(r.score)}`;
});

// --- NER -------------------------------------------------------------------------------------
const TAGS = { PER: 'person', PERSON: 'person', LOC: 'place', PLACE: 'place', ORG: 'organisation', ORGANIZATION: 'organisation', ORGANISATION: 'organisation' };
$('nerRun').onclick = () => run($('nerRun'), 'Finding names…', async () => {
    const text = $('nerIn').value;
    const { entities } = await bhashini.entities(text, $('nerLang').value, { serviceId: model('nerModel') });
    if (!entities.length) { $('nerOut').textContent = 'No names or places found.'; return; }
    const fragment = document.createDocumentFragment();
    entities.forEach((e, i) => {
        const mark = document.createElement('mark');
        mark.textContent = e.text;
        mark.append(Object.assign(document.createElement('small'), { textContent: TAGS[e.tag.slice(2)] || e.tag }));
        fragment.append(mark, i < entities.length - 1 ? '  ' : '');
    });
    $('nerOut').replaceChildren(fragment);
});

// --- OCR -------------------------------------------------------------------------------------
let ocrImage = null;
$('ocrFile').onchange = async event => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        ocrImage = reader.result.split(',')[1];
        $('ocrPreview').src = reader.result;
        $('ocrPreview').classList.remove('hidden');
        $('ocrUrl').value = '';
    };
    reader.readAsDataURL(file);
};
$('ocrRun').onclick = () => run($('ocrRun'), 'Reading the image… (5–15 s)', async () => {
    const imageUrl = $('ocrUrl').value.trim();
    if (!ocrImage && !imageUrl) throw new Error('Choose an image or paste an image URL.');
    const r = await bhashini.ocr({ imageBase64: imageUrl ? undefined : ocrImage, imageUrl: imageUrl || undefined, language: $('ocrLang').value, serviceId: model('ocrModel') });
    $('ocrOut').textContent = r.text;
});
$('ocrToTr').onclick = () => {
    $('trIn').value = $('ocrOut').textContent;
    $('trSrc').value = $('ocrLang').value;
    $('trTgt').value = $('ocrLang').value === 'en' ? 'hi' : 'en';
    showTab('translate');
};

// --- Saved transcripts -----------------------------------------------------------------------
async function loadSaved() {
    try {
        const items = await bhashini.listTranscripts();
        if (!items.length) { $('savedList').innerHTML = '<p class="muted">Nothing saved yet. Use 💾 Save on Speech → Text.</p>'; return; }
        $('savedList').replaceChildren(...items.map(item => {
            const div = document.createElement('div');
            div.className = 'saved-item';
            div.innerHTML = `
                <div class="head"><strong></strong><span class="meta"></span></div>
                <div class="text"></div>
                <div class="actions">
                    <a href="api/transcripts/${item.id}.txt">⬇ .txt</a>
                    <a href="api/transcripts/${item.id}.json">⬇ .json</a>
                    ${item.has_audio ? `<a href="api/transcripts/${item.id}.wav">⬇ .wav</a><audio controls preload="none" src="api/transcripts/${item.id}.wav"></audio>` : ''}
                    <button type="button">Delete</button>
                </div>`;
            div.querySelector('strong').textContent = item.title || item.id;
            div.querySelector('.meta').textContent = `${langName(item.language)} · ${item.source} · ${item.created.replace('T', ' ').slice(0, 16)}`;
            div.querySelector('.text').textContent = item.text;
            div.querySelector('button').onclick = async () => {
                if (!confirm('Delete this transcript and its audio?')) return;
                await bhashini.deleteTranscript(item.id);
                loadSaved();
            };
            return div;
        }));
    } catch (error) { status(`⚠ ${error.message}`, true); }
}
$('savedRefresh').onclick = loadSaved;

// --- Settings --------------------------------------------------------------------------------
const SERVICE_LABELS = {
    BHASHINI_ASR_SERVICE_ID: 'ASR', BHASHINI_NMT_SERVICE_ID: 'Translation', BHASHINI_TTS_SERVICE_ID: 'TTS',
    BHASHINI_XLIT_SERVICE_ID: 'Transliteration', BHASHINI_TLD_SERVICE_ID: 'Text language detection',
    BHASHINI_ALD_SERVICE_ID: 'Audio language detection', BHASHINI_NER_SERVICE_ID: 'NER',
    BHASHINI_OCR_SERVICE_ID: 'OCR', BHASHINI_DENOISER_SERVICE_ID: 'Denoiser',
    BHASHINI_STREAM_ASR_SERVICE_ID: 'Streaming ASR', BHASHINI_STREAM_URL: 'Streaming socket URL',
};
const SETTING_TASK = {
    BHASHINI_ASR_SERVICE_ID: 'asr', BHASHINI_NMT_SERVICE_ID: 'translation', BHASHINI_TTS_SERVICE_ID: 'tts',
    BHASHINI_XLIT_SERVICE_ID: 'transliteration', BHASHINI_TLD_SERVICE_ID: 'txt-lang-detection',
    BHASHINI_ALD_SERVICE_ID: 'audio-lang-detection', BHASHINI_NER_SERVICE_ID: 'ner', BHASHINI_OCR_SERVICE_ID: 'ocr',
    BHASHINI_DENOISER_SERVICE_ID: 'denoiser', BHASHINI_STREAM_ASR_SERVICE_ID: 'asr',
};
$('serviceFields').innerHTML = Object.entries(SERVICE_LABELS).map(([name, label]) =>
    `<label class="block">${label}<input name="${name}" autocomplete="off"${SETTING_TASK[name] ? ` list="models-${SETTING_TASK[name]}"` : ''}></label>`).join('')
    + Object.keys(TASK_NAMES).map(task => `<datalist id="models-${task}"></datalist>`).join('');
const fillDatalists = () => Object.entries(catalog.models).forEach(([task, list]) => {
    $(`models-${task}`)?.replaceChildren(...list.map(m => new Option(`${m.provider}${m.ok ? '' : ' ⚠'}`, m.id)));
});

function showKeyState(snapshot) {
    $('keyBadge').textContent = snapshot.key_set ? 'API key set' : 'No API key: open Settings';
    $('keyBadge').className = `badge ${snapshot.key_set ? 'ok' : 'bad'}`;
}
async function loadSettings() {
    const snapshot = await bhashini.post('/api/settings', undefined, 15000, 'GET');
    showKeyState(snapshot);
    if ($('confPath')) $('confPath').textContent = snapshot.path;
    for (const [name, value] of Object.entries(snapshot.values)) {
        const field = $('settingsForm').elements[name];
        if (field && name !== 'BHASHINI_API_KEY') field.value = value;
    }
    $('keyInput').placeholder = snapshot.key_set ? `current: ${snapshot.values.BHASHINI_API_KEY} (leave empty to keep)` : 'paste your Dhruva inference key';
    return snapshot;
}
$('settingsForm').onsubmit = event => {
    event.preventDefault();
    const button = event.submitter;
    run(button, 'Saving settings…', async () => {
        const values = Object.fromEntries(new FormData($('settingsForm')));
        showKeyState(await bhashini.post('/api/settings', values, 15000, 'PUT'));
        $('keyInput').value = '';
        await loadSettings();
        return '✓ Saved. Both services use the new settings right away.';
    });
};
$('testKey').onclick = () => run($('testKey'), 'Testing the key…', async () => {
    const r = await bhashini.post('/api/settings/test', {}, 30000);
    return `✓ Key works. "Hello" → ${r.sample}`;
});

// --- access code (hosted version) -----------------------------------------------------------
function askAccessCode(message = '') {
    $('accessError').textContent = message;
    $('accessGate').classList.remove('hidden');
    $('accessInput').focus();
}
$('accessForm').onsubmit = async event => {
    event.preventDefault();
    accessCode = $('accessInput').value.trim();
    try {
        await bhashini.post('/api/settings', undefined, 15000, 'GET');
        storage.set(accessCode);
        $('accessGate').classList.add('hidden');
        $('accessInput').value = '';
        await loadSettings();
        loadModels();
    } catch (error) {
        askAccessCode(error.status === 401 ? 'That code is not right.' : error.message);
    }
};

// --- boot ------------------------------------------------------------------------------------
async function boot() {
    const features = await fetch('/api/features').then(r => r.json()).catch(() => ({}));
    if (features.stream) $('streamLink').href = `${location.protocol}//${location.hostname}:8766/`;
    else $('streamLink').classList.add('hidden');
    if (features.transcripts === false) {
        document.querySelector('[data-tab=saved]').classList.add('hidden');
        $('asrSave').classList.add('hidden');
        $('asrKeepAudio').closest('label').classList.add('hidden');
    }
    if (features.settings_writable === false) {
        document.querySelectorAll('#settingsForm input, #settingsForm select, #settingsForm button[type=submit]').forEach(el => { el.disabled = true; });
        $('settingsHint').textContent = 'Hosted version: the API key and service IDs are set as environment variables on the host and cannot be changed here. Use Test key to check it.';
        $('testKey').disabled = false;
        if (accessCode) $('forgetCode').classList.remove('hidden');
    }
    showTab(location.hash.slice(1) && $('tabs').querySelector(`[data-tab="${location.hash.slice(1)}"]:not(.hidden)`) ? location.hash.slice(1) : 'asr');
    if (features.access_required && !accessCode) return askAccessCode();
    loadModels();
    loadSettings().then(s => { if (!s.key_set && features.settings_writable !== false) showTab('settings'); })
        .catch(error => { if (error.status === 401) askAccessCode('Your saved code no longer works.'); });
}
$('forgetCode').onclick = () => { storage.set(''); accessCode = ''; location.reload(); };
boot();
