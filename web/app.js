// Elements
const elStatus = document.getElementById('statusText');
const elTextContent = document.getElementById('textContent');
const elTextOverlay = document.getElementById('textOverlay');
const elModelSelect = document.getElementById('modelSelect');
const elNewsTopic = document.getElementById('newsTopic');

const btnGenerate = document.getElementById('btnGenerate');
const btnSpeak = document.getElementById('btnSpeak');
const btnPause = document.getElementById('btnPause');

// State
let audioQueue = [];
let isPlaying = false;
let isPaused = false;
let currentAudio = null;
let currentBoundaries = [];
let currentChunkIndex = 0;
let synthesisActive = false;
let animationFrameId = null;

// ====================================================
// Text Mirroring (Editor Sync)
// ====================================================

function updateOverlay() {
    elTextOverlay.textContent = elTextContent.value;
}
elTextContent.addEventListener('input', updateOverlay);
elTextContent.addEventListener('scroll', () => {
    elTextOverlay.scrollTop = elTextContent.scrollTop;
});

// ====================================================
// Generative AI
// ====================================================
btnGenerate.addEventListener('click', async () => {
    const topic = elNewsTopic.value.trim();
    const modelId = elModelSelect.value;

    if (!topic) {
        alert("Please enter a topic for the news.");
        return;
    }

    btnGenerate.disabled = true;
    elStatus.textContent = "AI is writing the article... Please wait.";

    try {
        const response = await fetch('/api/generate_news', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: topic, model_id: modelId })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "API Error");
        }

        const data = await response.json();

        // Populate text box
        elTextContent.value = data.article;
        updateOverlay();
        elStatus.textContent = "Article Generated! Press 'Speak Text' to listen.";

    } catch (error) {
        alert("Failed to generate news: " + error.message);
        elStatus.textContent = "Error generating news.";
    } finally {
        btnGenerate.disabled = false;
    }
});

// ====================================================
// Text to Speech and Playback
// ====================================================

function splitTextIntoSentences(text) {
    // Basic sentence chunking over newlines or periods
    return text.split(/([.\n]+)/).filter(s => s.trim().length > 0);
}

btnSpeak.addEventListener('click', async () => {
    if (isPaused && currentAudio) {
        // Resume
        currentAudio.play();
        isPaused = false;
        btnPause.textContent = "⏸ Pause";
        elStatus.textContent = "Playing...";
        requestAnimationFrame(updateHighlight);
        return;
    }

    const fullText = elTextContent.value.trim();
    if (!fullText) return;

    // Reset State
    stopPlayback();
    btnSpeak.disabled = true;
    btnPause.disabled = false;

    sysnthesizeChunks(fullText);
});

btnPause.addEventListener('click', () => {
    if (!isPlaying || !currentAudio) return;

    if (isPaused) {
        currentAudio.play();
        isPaused = false;
        btnPause.textContent = "⏸ Pause";
        elStatus.textContent = "Playing...";
        requestAnimationFrame(updateHighlight);
    } else {
        currentAudio.pause();
        isPaused = true;
        btnPause.textContent = "▶ Resume";
        elStatus.textContent = "Paused.";
        cancelAnimationFrame(animationFrameId);
    }
});

function stopPlayback() {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    cancelAnimationFrame(animationFrameId);
    audioQueue = [];
    isPlaying = false;
    isPaused = false;
    synthesisActive = false;
    btnSpeak.disabled = false;
    btnPause.disabled = true;
    btnPause.textContent = "⏸ Pause";
    updateOverlay(); // reset highlights
}

// Split text into sentences for chunked playback, tracking exact start offset in fullText
function splitIntoSentences(fullText) {
    const result = [];
    const chunks = fullText.match(/[^.!?\n]+[.!?\n]*/g) || [fullText];
    let searchFrom = 0;
    for (const chunk of chunks) {
        const trimmed = chunk.trim();
        if (trimmed.length <= 2) continue;
        const idx = fullText.indexOf(trimmed, searchFrom);
        if (idx === -1) continue;
        result.push({ text: trimmed, offset: idx });
        searchFrom = idx + trimmed.length;
    }
    return result;
}

// Fetch one chunk of TTS audio from the server
async function fetchAudioChunk(text, voice, rate) {
    const response = await fetch('/api/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice, rate })
    });
    if (!response.ok) throw new Error("Server error on chunk");
    return response.json();
}

// Chunk offset tracker for highlight alignment
let chunkTextOffset = 0;
let sentenceQueue = [];
let sentenceIndex = 0;

async function sysnthesizeChunks(fullText) {
    synthesisActive = true;
    isPlaying = true;
    elStatus.textContent = "Preparing audio...";

    const voice = document.getElementById('voiceSelect').value;
    const rate = document.getElementById('speedSelect').value;

    // Gemini: send full text at once (API limitation)
    if (voice.startsWith("gemini-")) {
        try {
            const data = await fetchAudioChunk(fullText, voice, rate);
            currentBoundaries = data.boundaries;
            currentAudio = new Audio(data.audio_url);
            if (rate === "-20%") currentAudio.playbackRate = 0.8;
            else if (rate === "-10%") currentAudio.playbackRate = 0.9;
            else if (rate === "+10%") currentAudio.playbackRate = 1.1;
            else if (rate === "+20%") currentAudio.playbackRate = 1.2;
            else currentAudio.playbackRate = 1.0;
            currentAudio.onended = () => { stopPlayback(); elStatus.textContent = "Finished reading."; };
            currentAudio.play();
            elStatus.textContent = "Playing...";
            requestAnimationFrame(updateHighlight);
        } catch (e) {
            alert("Audio synthesis failed: " + e.message);
            stopPlayback();
        }
        return;
    }

    // edge-tts: process sentence by sentence with pre-fetching
    sentenceQueue = splitIntoSentences(fullText);
    sentenceIndex = 0;

    async function playNextChunk() {
        if (!synthesisActive || sentenceIndex >= sentenceQueue.length) {
            if (synthesisActive) { stopPlayback(); elStatus.textContent = "Finished reading."; }
            return;
        }

        const sentObj = sentenceQueue[sentenceIndex];
        const sentence = sentObj.text;
        const myOffset = sentObj.offset; // exact char position in fullText

        try {
            const data = await fetchAudioChunk(sentence, voice, rate);
            if (!synthesisActive) return;

            // Adjust boundary offsets — use exact offset from indexOf, not approximation
            currentBoundaries = (data.boundaries || []).map(b => ({
                ...b,
                text_index_start: b.text_index_start + myOffset,
                text_index_end: b.text_index_end + myOffset,
            }));

            currentAudio = new Audio(data.audio_url);
            sentenceIndex++;

            // Pre-fetch next chunk in background while current plays
            let nextData = null;
            if (sentenceIndex < sentenceQueue.length) {
                fetchAudioChunk(sentenceQueue[sentenceIndex].text, voice, rate)
                    .then(d => { nextData = d; })
                    .catch(() => { });
            }

            currentAudio.onended = () => {
                cancelAnimationFrame(animationFrameId);
                if (nextData && synthesisActive && sentenceIndex < sentenceQueue.length) {
                    const nextSentObj = sentenceQueue[sentenceIndex];
                    currentBoundaries = (nextData.boundaries || []).map(b => ({
                        ...b,
                        text_index_start: b.text_index_start + nextSentObj.offset,
                        text_index_end: b.text_index_end + nextSentObj.offset,
                    }));
                    currentAudio = new Audio(nextData.audio_url);
                    sentenceIndex++;
                    currentAudio.onended = () => { cancelAnimationFrame(animationFrameId); playNextChunk(); };
                    currentAudio.play();
                    elStatus.textContent = `Playing... (${sentenceIndex}/${sentenceQueue.length})`;
                    requestAnimationFrame(updateHighlight);
                } else {
                    playNextChunk();
                }
            };

            currentAudio.play();
            elStatus.textContent = `Playing... (${sentenceIndex}/${sentenceQueue.length})`;
            requestAnimationFrame(updateHighlight);

        } catch (e) {
            alert("Audio synthesis failed: " + e.message);
            stopPlayback();
        }
    }

    playNextChunk();
}


// ====================================================
// Highlight Engine
// ====================================================
function updateHighlight() {
    if (!isPlaying || isPaused || !currentAudio) return;

    const currentTimeMs = currentAudio.currentTime * 1000;
    const fullText = elTextContent.value;

    // Find active boundary
    let targetWb = null;
    let targetIndex = -1;
    for (let i = 0; i < currentBoundaries.length; i++) {
        if (currentTimeMs >= currentBoundaries[i].start_time_ms &&
            currentTimeMs <= currentBoundaries[i].end_time_ms) {
            targetWb = currentBoundaries[i];
            targetIndex = i;
            break;
        }
    }

    if (targetWb) {
        const before = fullText.slice(0, targetWb.text_index_start);
        const current = fullText.slice(targetWb.text_index_start, targetWb.text_index_end);
        const after = fullText.slice(targetWb.text_index_end);

        // Rebuild html string
        const html = `<span class="highlight-spoken">${escapeHtml(before)}</span>` +
            `<span class="highlight-current-word">${escapeHtml(current)}</span>` +
            `<span>${escapeHtml(after)}</span>`;

        elTextOverlay.innerHTML = html;

        // simple auto scroll roughly to middle of text block
        const span = elTextOverlay.querySelector('.highlight-current-word');
        if (span) {
            const ot = span.offsetTop;
            const h = elTextContent.clientHeight;
            elTextContent.scrollTop = ot - (h / 2);
            elTextOverlay.scrollTop = ot - (h / 2);
        }
    }

    animationFrameId = requestAnimationFrame(updateHighlight);
}

function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}
