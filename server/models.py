"""Bhashini models (service IDs) people can pick per task, with the languages each supports.

Source: https://dibd-bhashini.gitbook.io/bhashini-apis/available-models-for-usage
`ok` is the result of calling each model with this kit's key on 2026-10-14 (False = Dhruva
returned an error then; the model is still listed so it can be retried later).
Languages use the kit's codes; ones the kit does not offer (e.g. Haryanvi, Bhili) are left out.
"""

def _codes(text):
    return text.split()


INDICTRANS = _codes('en kok gu sa te mr hi or mni ml as doi sat ta sd bn ks kn ne')
ALL_22 = _codes('as bn brx doi gu hi kn ks kok mai ml mni mr ne or pa sa sat sd ta te ur')

MODELS = {
    'asr': [
        {'id': 'bhashini/bodhan/asr-transcribe-flex', 'provider': 'Bodhan.AI', 'languages': ['en', *ALL_22, 'bho', 'hne'], 'ok': True},
        {'id': 'bhashini/bodhan/asr-transcribe-core', 'provider': 'Bodhan.AI', 'languages': ['en', *ALL_22, 'bho'], 'ok': True},
        {'id': 'bhashini/ai4bharat/conformer-multilingual-asr', 'provider': 'AI4Bharat', 'languages': ALL_22, 'ok': True},
        {'id': 'ai4bharat/conformer-hi-gpu--t4', 'provider': 'AI4Bharat', 'languages': ['hi'], 'ok': True},
        {'id': 'ai4bharat/conformer-multilingual-indo_aryan-gpu--t4', 'provider': 'AI4Bharat', 'languages': _codes('hi bn mr ur or pa gu sa'), 'ok': True},
        {'id': 'ai4bharat/conformer-multilingual-dravidian-gpu--t4', 'provider': 'AI4Bharat', 'languages': _codes('kn ml ta te'), 'ok': True},
        {'id': 'ai4bharat/whisper-medium-en--gpu--t4', 'provider': 'AI4Bharat', 'languages': ['en'], 'ok': True},
        {'id': 'bhashini/iitm/asr-indoaryan--gpu--t4', 'provider': 'IIT Madras', 'languages': _codes('gu or hi mr pa bn'), 'ok': True},
        {'id': 'bhashini/iitm/asr-dravidian--gpu--t4', 'provider': 'IIT Madras', 'languages': _codes('te kn ml ta'), 'ok': True},
        {'id': 'bhashini/iitm/asr-misc--gpu--t4', 'provider': 'IIT Madras', 'languages': _codes('bho ur'), 'ok': True},
        {'id': 'bhashini/iisc/asr-bho-t4', 'provider': 'IISc', 'languages': ['bho'], 'ok': True},
        {'id': 'bhashini/iisc/asr-mai-t4', 'provider': 'IISc', 'languages': ['mai'], 'ok': False},
    ],
    'translation': [
        {'id': 'bhashini/iiith/nmt-all', 'provider': 'IIIT Hyderabad', 'ok': True,
         'source': ['en', *ALL_22, 'bho', 'mag'], 'target': ['en', *ALL_22, 'bho', 'mag']},
        {'id': 'ai4bharat/indictrans-v2-all-gpu--t4', 'provider': 'AI4Bharat', 'ok': True, 'source': INDICTRANS, 'target': INDICTRANS},
        {'id': 'bhashini/bodhan/Indic-trans-v4', 'provider': 'Bodhan.AI', 'ok': True, 'source': INDICTRANS, 'target': INDICTRANS},
        {'id': 'Bhashini/IIITH/Trans/V1', 'provider': 'IIIT Hyderabad', 'ok': True,
         'source': _codes('hi en te or gu ur'), 'target': _codes('pa hi en te ur gu or sd doi ks')},
        {'id': 'bhashini/aukbc/disco-nmt', 'provider': 'AU-KBC', 'ok': True, 'source': _codes('ml hi ta en kn'), 'target': _codes('ml hi ta en kn')},
        {'id': 'bhashini/cdac-noida/nmt', 'provider': 'CDAC Noida', 'ok': True, 'source': _codes('en hi ta or bn'), 'target': _codes('en hi ta or bn')},
        {'id': 'bhashini/cdac-pune/nmt', 'provider': 'CDAC Pune', 'ok': True, 'source': _codes('en kn gu ml mr hi'), 'target': _codes('en kn gu ml mr hi')},
        {'id': 'bhashini/iitkhg/nmt', 'provider': 'IIT Kharagpur', 'ok': True, 'source': ['hi'], 'target': ['sa', 'kn']},
        {'id': 'bhashini/iiith/santham/nmt', 'provider': 'IIIT Hyderabad', 'ok': True, 'source': ['sa'], 'target': ['ta']},
        {'id': 'iitb/trilingual-en_hi_mr-v1-gpu--t4', 'provider': 'IIT Bombay', 'ok': False,
         'source': _codes('en as mr hi'), 'target': _codes('as hi brx ne en mr mai kok')},
    ],
    'transliteration': [
        {'id': 'ai4bharat/indicxlit--cpu-fsv2', 'provider': 'AI4Bharat', 'ok': True,
         'source': [*INDICTRANS, 'pa', 'mai', 'ur', 'brx'], 'target': [*INDICTRANS, 'pa', 'mai', 'ur', 'brx']},
    ],
    'tts': [
        {'id': 'Bhashini/IITM/TTS', 'provider': 'IIT Madras', 'languages': ['en', *ALL_22, 'raj'], 'ok': True},
        {'id': 'Bhashini/IISC/TTS', 'provider': 'IISc (SYSPIN)', 'languages': _codes('kn te en hi mr bn gu mai bho hne mag'), 'ok': True},
        {'id': 'bhashini/bodhan/indic-tts', 'provider': 'Bodhan.AI', 'languages': INDICTRANS, 'ok': True},
        {'id': 'ai4bharat/indic-tts-coqui-indo_aryan-gpu--t4', 'provider': 'AI4Bharat', 'languages': _codes('hi mr as bn gu or raj pa'), 'ok': True},
        {'id': 'ai4bharat/indic-tts-coqui-dravidian-gpu--t4', 'provider': 'AI4Bharat', 'languages': _codes('ml kn ta te'), 'ok': True},
        {'id': 'ai4bharat/indic-tts-coqui-misc-gpu--t4', 'provider': 'AI4Bharat', 'languages': _codes('en mni brx'), 'ok': True},
        {'id': 'bhashini/iisc/sourashtra/tts', 'provider': 'IISc', 'languages': ['ta'], 'ok': True},
    ],
    'audio-lang-detection': [
        {'id': 'bhashini/iitmandi/audio-lang-detection/gpu', 'provider': 'IIT Mandi', 'languages': _codes('as bn en hi kn gu ml mr or pa ta te'), 'ok': True},
        {'id': 'bhashini/ald', 'provider': 'Bhashini', 'languages': INDICTRANS[1:], 'ok': True},
    ],
    'txt-lang-detection': [
        {'id': 'bhashini/indic-lang-detection-all', 'provider': 'AI4Bharat', 'languages': ['en', *ALL_22], 'ok': True},
        {'id': 'bhashini/iiiith/indic-lang-detection-all', 'provider': 'IIIT Hyderabad', 'languages': _codes('as bn en gu hi kn ml mni mr or pa ta te ur'), 'ok': True},
        {'id': 'bhashini/indic/tld', 'provider': 'Bhashini', 'languages': ['en', *ALL_22], 'ok': True},
    ],
    'ner': [
        {'id': 'bhashini/ai4bharat/indic-ner', 'provider': 'AI4Bharat', 'languages': _codes('as bn gu hi kn ml te mr or pa ta'), 'ok': True},
        {'id': 'bhashini/aukbc/ner', 'provider': 'AU-KBC', 'languages': _codes('hi bn mr pa kn ml ta en'), 'ok': True},
        {'id': 'bhashini/iiith/ner', 'provider': 'IIIT Hyderabad', 'languages': _codes('hi ur or te'), 'ok': True},
    ],
    'ocr': [
        {'id': 'bhashini/bodhan/indic-doc/ocr', 'provider': 'Bodhan.AI', 'note': 'printed + handwritten', 'languages': ['en', *ALL_22], 'ok': True},
        {'id': 'bhashini/iiith-ocr-sceneText-all', 'provider': 'IIIT Hyderabad', 'note': 'scene text: signs, photos', 'languages': _codes('as bn gu hi kn ml mni mr or pa ta te ur'), 'ok': True},
        {'id': 'bhashini/iiith-bhasha-ocr', 'provider': 'IIIT Hyderabad', 'note': 'printed', 'languages': [c for c in ['en', *ALL_22] if c not in ('ur',)], 'ok': False},
        {'id': 'bhashini/iiith/ocr-hw-bhaasha', 'provider': 'IIIT Hyderabad', 'note': 'handwritten', 'languages': _codes('bn hi ml mr pa te kn ta'), 'ok': False},
    ],
}
# The denoiser is not in the published list; this is the ID from the Postman collection.
MODELS['denoiser'] = [{'id': 'bhashini/facebook/denoiser--gpu-t4', 'provider': 'Meta (Bhashini-hosted)', 'languages': [], 'ok': True}]


def find(task, service_id):
    return next((m for m in MODELS.get(task, []) if m['id'] == service_id), None)


def supports(model, source=None, target=None):
    """Whether a catalog model handles a language (or a source/target pair for NMT/transliteration)."""
    if 'source' in model:
        return (source is None or source in model['source']) and (target is None or target in model['target'])
    return source is None or not model['languages'] or source in model['languages']


def first_for(task, source=None, target=None):
    """First working model for a language, used when the configured default can't handle it."""
    return next((m['id'] for m in MODELS.get(task, []) if m['ok'] and supports(m, source, target)), '')
