// AudioWorklet: forwards raw mono Float32 microphone samples to the main thread.
// Must be served as its own file (browsers load worklets by URL).
class BhashiniPcmCapture extends AudioWorkletProcessor {
    process(inputs) {
        const samples = inputs[0]?.[0];
        if (samples?.length) this.port.postMessage(new Float32Array(samples));
        return true;
    }
}
registerProcessor('bhashini-pcm-capture', BhashiniPcmCapture);
