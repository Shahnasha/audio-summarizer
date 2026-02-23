/* ═══════════════════════════════════════════════════════════════
   VOX — Client-Side Logic (with Audio Recorder)
   ═══════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  // ── DOM refs ────────────────────────────────────────────────
  const dropzone       = document.getElementById("dropzone");
  const fileInput      = document.getElementById("file-input");
  const browseBtn      = document.getElementById("browse-btn");
  const filePreview    = document.getElementById("file-preview");
  const fileName       = document.getElementById("file-name");
  const fileMeta       = document.getElementById("file-meta");
  const clearBtn       = document.getElementById("clear-btn");
  const processBtn     = document.getElementById("process-btn");
  const uploadZone     = document.getElementById("upload-zone");
  const processing     = document.getElementById("processing");
  const processingStep = document.getElementById("processing-step");
  const errorSection   = document.getElementById("error-section");
  const errorMsg       = document.getElementById("error-msg");
  const retryBtn       = document.getElementById("retry-btn");
  const results        = document.getElementById("results");
  const newUploadBtn   = document.getElementById("new-upload-btn");
  const downloadBtn    = document.getElementById("download-btn");
  const toast          = document.getElementById("toast");
  const toastMsg       = document.getElementById("toast-msg");

  // Tabs
  const tabUpload      = document.getElementById("tab-upload");
  const tabRecord      = document.getElementById("tab-record");

  // Recorder
  const recorderPanel  = document.getElementById("recorder-panel");
  const waveCanvas     = document.getElementById("waveform-canvas");
  const recTimer       = document.getElementById("rec-timer");
  const recStartBtn    = document.getElementById("rec-start-btn");
  const recStopBtn     = document.getElementById("rec-stop-btn");
  const recPauseBtn    = document.getElementById("rec-pause-btn");
  const recHint        = document.getElementById("rec-hint");
  const recPreview     = document.getElementById("rec-preview");
  const recMeta        = document.getElementById("rec-meta");
  const recAudioPlayer = document.getElementById("rec-audio-player");
  const recDiscardBtn  = document.getElementById("rec-discard-btn");
  const recProcessBtn  = document.getElementById("rec-process-btn");

  let selectedFile   = null;
  let fullTranscript = "";

  // ── Recorder state ──────────────────────────────────────────
  let mediaRecorder  = null;
  let audioStream    = null;
  let audioContext    = null;
  let analyser       = null;
  let animFrameId    = null;
  let recordedChunks = [];
  let recordedBlob   = null;
  let recStartTime   = 0;
  let recElapsed     = 0;
  let timerInterval  = null;
  let isPaused       = false;

  // ── Helpers ─────────────────────────────────────────────────
  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatDuration(sec) {
    if (!sec || sec <= 0) return "—";
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return m > 0 ? m + "m " + s + "s" : s + "s";
  }

  function formatTimerDisplay(totalSec) {
    const m = Math.floor(totalSec / 60);
    const s = Math.floor(totalSec % 60);
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function showToast(msg, duration) {
    duration = duration || 2200;
    toastMsg.textContent = msg;
    show(toast);
    toast.classList.add("show");
    setTimeout(function () {
      toast.classList.remove("show");
      setTimeout(function () { hide(toast); }, 300);
    }, duration);
  }

  // ══════════════════════════════════════════════════════════════
  //  MODE TABS
  // ══════════════════════════════════════════════════════════════

  function switchMode(mode) {
    tabUpload.classList.toggle("active", mode === "upload");
    tabRecord.classList.toggle("active", mode === "record");

    if (mode === "upload") {
      show(dropzone);
      hide(recorderPanel);
      hide(recPreview);
      stopRecordingCleanup();
    } else {
      hide(dropzone);
      hide(filePreview);
      show(recorderPanel);
      hide(recPreview);
      selectedFile = null;
      fileInput.value = "";
      sizeCanvas();
      stopWaveform(); // draw flat line
    }
  }

  tabUpload.addEventListener("click", function () { switchMode("upload"); });
  tabRecord.addEventListener("click", function () { switchMode("record"); });

  // ══════════════════════════════════════════════════════════════
  //  FILE UPLOAD
  // ══════════════════════════════════════════════════════════════

  function handleFileSelected(file) {
    if (!file) return;

    var parts = file.name.split(".");
    var ext = "." + parts[parts.length - 1].toLowerCase();
    var allowed = [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"];
    if (allowed.indexOf(ext) === -1) {
      showError("Invalid file type. Allowed: WAV, MP3, M4A, FLAC, OGG, WebM");
      return;
    }

    selectedFile = file;
    fileName.textContent = file.name;
    fileMeta.textContent = formatSize(file.size) + "  ·  " + ext.toUpperCase().slice(1);

    hide(dropzone);
    hide(recorderPanel);
    hide(recPreview);
    show(filePreview);
  }

  function resetToUpload() {
    selectedFile = null;
    recordedBlob = null;
    fullTranscript = "";
    fileInput.value = "";

    stopRecordingCleanup();

    show(uploadZone);
    show(dropzone);
    hide(filePreview);
    hide(recorderPanel);
    hide(recPreview);
    hide(processing);
    hide(errorSection);
    hide(results);

    tabUpload.classList.add("active");
    tabRecord.classList.remove("active");
  }

  // Drag & Drop
  dropzone.addEventListener("click", function () { fileInput.click(); });
  browseBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    fileInput.click();
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files.length) handleFileSelected(fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", function (e) {
    if (e.dataTransfer.files.length) handleFileSelected(e.dataTransfer.files[0]);
  });

  clearBtn.addEventListener("click", resetToUpload);
  retryBtn.addEventListener("click", resetToUpload);
  newUploadBtn.addEventListener("click", resetToUpload);

  // ══════════════════════════════════════════════════════════════
  //  AUDIO RECORDER
  // ══════════════════════════════════════════════════════════════

  // ── Canvas sizing ───────────────────────────────────────────
  function sizeCanvas() {
    if (!waveCanvas) return;
    var rect = waveCanvas.getBoundingClientRect();
    waveCanvas.width = rect.width * (window.devicePixelRatio || 1);
    waveCanvas.height = rect.height * (window.devicePixelRatio || 1);
  }

  window.addEventListener("resize", function () {
    if (!recorderPanel.hidden) sizeCanvas();
  });

  // ── Waveform Visualizer ─────────────────────────────────────
  function drawWaveform() {
    if (!analyser || !waveCanvas) return;

    var ctx = waveCanvas.getContext("2d");
    var bufLen = analyser.frequencyBinCount;
    var dataArray = new Uint8Array(bufLen);

    function draw() {
      animFrameId = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);

      // Read dimensions each frame so resize is picked up
      var W = waveCanvas.width;
      var H = waveCanvas.height;

      // Background
      ctx.fillStyle = "#0c0b0f";
      ctx.fillRect(0, 0, W, H);

      // Waveform line
      var isRec = mediaRecorder && mediaRecorder.state === "recording";
      ctx.lineWidth = 2;
      ctx.strokeStyle = isRec ? "#e8a44a" : "#6b6780";
      ctx.beginPath();

      var sliceW = W / bufLen;
      var x = 0;
      for (var i = 0; i < bufLen; i++) {
        var v = dataArray[i] / 128.0;
        var y = (v * H) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceW;
      }
      ctx.lineTo(W, H / 2);
      ctx.stroke();

      // Center line
      ctx.strokeStyle = "#2a283366";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, H / 2);
      ctx.lineTo(W, H / 2);
      ctx.stroke();
    }

    draw();
  }

  function stopWaveform() {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
    if (waveCanvas) {
      var ctx = waveCanvas.getContext("2d");
      var W = waveCanvas.width;
      var H = waveCanvas.height;
      ctx.fillStyle = "#0c0b0f";
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "#2a2833";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, H / 2);
      ctx.lineTo(W, H / 2);
      ctx.stroke();
    }
  }

  // ── Timer ───────────────────────────────────────────────────
  function startTimer() {
    recStartTime = Date.now() - recElapsed * 1000;
    timerInterval = setInterval(function () {
      recElapsed = (Date.now() - recStartTime) / 1000;
      recTimer.textContent = formatTimerDisplay(recElapsed);
    }, 200);
  }

  function stopTimer() {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  // ── Start Recording ─────────────────────────────────────────
  recStartBtn.addEventListener("click", async function () {
    try {
      audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        },
      });
    } catch (err) {
      showToast("Microphone access denied", 3000);
      recHint.textContent = "Please allow microphone access and try again";
      return;
    }

    // Audio context + analyser
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    var source = audioContext.createMediaStreamSource(audioStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);

    sizeCanvas();
    drawWaveform();

    // MIME type
    var mimeType = "";
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
      mimeType = "audio/webm;codecs=opus";
    } else if (MediaRecorder.isTypeSupported("audio/webm")) {
      mimeType = "audio/webm";
    } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
      mimeType = "audio/ogg;codecs=opus";
    }

    recordedChunks = [];
    mediaRecorder = new MediaRecorder(audioStream, mimeType ? { mimeType: mimeType } : {});

    mediaRecorder.ondataavailable = function (e) {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };

    mediaRecorder.onstop = function () {
      var mType = mediaRecorder.mimeType || "audio/webm";
      recordedBlob = new Blob(recordedChunks, { type: mType });
      // Clean up stream AFTER blob is assembled
      cleanupStream();
      onRecordingComplete();
    };

    mediaRecorder.start(250);
    isPaused = false;
    recElapsed = 0;
    startTimer();

    // UI
    hide(recStartBtn);
    show(recStopBtn);
    show(recPauseBtn);
    recTimer.classList.add("recording");
    recHint.textContent = "Recording… speak into your microphone";
  });

  // ── Pause / Resume ──────────────────────────────────────────
  recPauseBtn.addEventListener("click", function () {
    if (!mediaRecorder) return;

    if (mediaRecorder.state === "recording") {
      mediaRecorder.pause();
      isPaused = true;
      stopTimer();
      recPauseBtn.classList.add("paused");
      recPauseBtn.title = "Resume";
      recHint.textContent = "Paused — click to resume";
      recPauseBtn.innerHTML =
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
    } else if (mediaRecorder.state === "paused") {
      mediaRecorder.resume();
      isPaused = false;
      startTimer();
      recPauseBtn.classList.remove("paused");
      recPauseBtn.title = "Pause";
      recHint.textContent = "Recording… speak into your microphone";
      recPauseBtn.innerHTML =
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
    }
  });

  // ── Stop Recording ──────────────────────────────────────────
  recStopBtn.addEventListener("click", function () {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    stopTimer();
    stopWaveform();
    // NOTE: cleanupStream() is called inside mediaRecorder.onstop
    // to ensure all audio data is captured before closing the stream

    recTimer.classList.remove("recording");
    recStartBtn.classList.remove("recording");
    recPauseBtn.classList.remove("paused");
    hide(recStopBtn);
    hide(recPauseBtn);
    show(recStartBtn);
    recPauseBtn.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
  });

  function cleanupStream() {
    if (audioStream) {
      audioStream.getTracks().forEach(function (t) { t.stop(); });
      audioStream = null;
    }
    if (audioContext) {
      audioContext.close().catch(function () {});
      audioContext = null;
      analyser = null;
    }
  }

  function stopRecordingCleanup() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try { mediaRecorder.stop(); } catch (e) {}
    }
    stopTimer();
    stopWaveform();
    cleanupStream();
    mediaRecorder = null;
    recordedChunks = [];
    recordedBlob = null;
    recElapsed = 0;
    isPaused = false;

    recTimer.textContent = "00:00";
    recTimer.classList.remove("recording");
    recStartBtn.classList.remove("recording");
    recPauseBtn.classList.remove("paused");
    hide(recStopBtn);
    hide(recPauseBtn);
    show(recStartBtn);
    recHint.textContent = "Click the red button to start recording";
  }

  // ── Recording Complete ──────────────────────────────────────
  function onRecordingComplete() {
    if (!recordedBlob) return;

    var url = URL.createObjectURL(recordedBlob);
    recAudioPlayer.src = url;
    recMeta.textContent =
      formatSize(recordedBlob.size) + "  ·  " + formatTimerDisplay(recElapsed);

    hide(recorderPanel);
    show(recPreview);
  }

  // Discard
  recDiscardBtn.addEventListener("click", function () {
    recordedBlob = null;
    recordedChunks = [];
    recElapsed = 0;
    recTimer.textContent = "00:00";
    recAudioPlayer.src = "";

    hide(recPreview);
    show(recorderPanel);
    recHint.textContent = "Click the red button to start recording";
  });

  // Process recording — convert to WAV in browser (no ffmpeg needed)
  recProcessBtn.addEventListener("click", async function () {
    if (!recordedBlob) return;

    // Save original button content and disable
    var originalHTML = recProcessBtn.innerHTML;
    recProcessBtn.disabled = true;
    recProcessBtn.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin-icon"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Converting…';

    try {
      var wavBlob = await convertBlobToWav(recordedBlob);
      var recFile = new File([wavBlob], "recording.wav", { type: "audio/wav" });
      selectedFile = recFile;
      recProcessBtn.disabled = false;
      recProcessBtn.innerHTML = originalHTML;
      submitAudio();
    } catch (err) {
      recProcessBtn.disabled = false;
      recProcessBtn.innerHTML = originalHTML;
      showError("Failed to process recording: " + err.message);
    }
  });

  // ══════════════════════════════════════════════════════════════
  //  BROWSER-SIDE WAV CONVERSION (eliminates ffmpeg dependency)
  // ══════════════════════════════════════════════════════════════

  /**
   * Decode a recorded audio Blob (WebM/OGG) to PCM and re-encode as WAV.
   * Uses the Web Audio API — works entirely in the browser.
   */
  function convertBlobToWav(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("Could not read recording")); };
      reader.onload = function () {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.decodeAudioData(reader.result)
          .then(function (audioBuffer) {
            var wavBlob = audioBufferToWav(audioBuffer);
            ctx.close();
            resolve(wavBlob);
          })
          .catch(function (e) {
            ctx.close();
            reject(new Error("Could not decode audio: " + e.message));
          });
      };
      reader.readAsArrayBuffer(blob);
    });
  }

  /**
   * Encode an AudioBuffer as a 16-bit mono WAV Blob.
   */
  function audioBufferToWav(buffer) {
    var numChannels = 1;
    var sampleRate = buffer.sampleRate;
    var samples;

    // Mix down to mono if stereo
    if (buffer.numberOfChannels > 1) {
      var left = buffer.getChannelData(0);
      var right = buffer.getChannelData(1);
      samples = new Float32Array(left.length);
      for (var i = 0; i < left.length; i++) {
        samples[i] = (left[i] + right[i]) * 0.5;
      }
    } else {
      samples = buffer.getChannelData(0);
    }

    var dataLength = samples.length * 2; // 16-bit = 2 bytes
    var arrayBuffer = new ArrayBuffer(44 + dataLength);
    var view = new DataView(arrayBuffer);

    // ── WAV header ──
    wavWriteStr(view, 0, "RIFF");
    view.setUint32(4, 36 + dataLength, true);
    wavWriteStr(view, 8, "WAVE");

    // fmt chunk
    wavWriteStr(view, 12, "fmt ");
    view.setUint32(16, 16, true);              // chunk size
    view.setUint16(20, 1, true);               // PCM format
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true); // byte rate
    view.setUint16(32, numChannels * 2, true); // block align
    view.setUint16(34, 16, true);              // bits per sample

    // data chunk
    wavWriteStr(view, 36, "data");
    view.setUint32(40, dataLength, true);

    // Write 16-bit PCM samples
    var offset = 44;
    for (var i = 0; i < samples.length; i++) {
      var s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      offset += 2;
    }

    return new Blob([arrayBuffer], { type: "audio/wav" });
  }

  function wavWriteStr(view, offset, str) {
    for (var i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  SUBMIT & PROCESS
  // ══════════════════════════════════════════════════════════════

  var STEPS = [
    "Converting audio format",
    "Running speech recognition",
    "Analyzing transcript",
    "Generating summary",
    "Extracting keywords",
  ];

  processBtn.addEventListener("click", function () {
    if (!selectedFile) return;
    submitAudio();
  });

  async function submitAudio() {
    if (!selectedFile) return;

    hide(uploadZone);
    hide(errorSection);
    hide(results);
    show(processing);

    var stepIdx = 0;
    processingStep.textContent = STEPS[0];
    var stepInterval = setInterval(function () {
      stepIdx = Math.min(stepIdx + 1, STEPS.length - 1);
      processingStep.textContent = STEPS[stepIdx];
    }, 3000);

    try {
      var formData = new FormData();
      formData.append("audio", selectedFile);

      var resp = await fetch("/process", {
        method: "POST",
        body: formData,
      });

      clearInterval(stepInterval);

      var data = await resp.json();

      if (!resp.ok || data.error) {
        showError(data.error || "Unknown error occurred");
        return;
      }

      renderResults(data);
    } catch (err) {
      clearInterval(stepInterval);
      showError("Network error: " + err.message);
    }
  }

  // ── Error ───────────────────────────────────────────────────
  function showError(msg) {
    hide(processing);
    hide(results);
    hide(uploadZone);
    show(errorSection);
    errorMsg.textContent = msg;
  }

  // ── Render Results ──────────────────────────────────────────
  function renderResults(data) {
    hide(processing);
    hide(uploadZone);
    hide(errorSection);
    show(results);

    fullTranscript = data.transcript || "";

    // Stats
    var stats = data.stats || {};
    document.getElementById("stat-words").textContent =
      stats.word_count != null ? stats.word_count.toLocaleString() : "—";
    document.getElementById("stat-sentences").textContent =
      stats.sentence_count != null ? stats.sentence_count : "—";
    document.getElementById("stat-duration").textContent =
      formatDuration(stats.duration_sec);
    document.getElementById("stat-reading").textContent =
      stats.reading_time_min != null ? stats.reading_time_min + " min" : "—";

    // Summary
    document.getElementById("summary-text").textContent =
      data.summary || "No summary available.";

    // Keywords
    var cloud = document.getElementById("keywords-cloud");
    cloud.innerHTML = "";
    (data.keywords || []).forEach(function (kw, i) {
      var tag = document.createElement("span");
      tag.className = "keyword-tag";
      tag.style.animationDelay = i * 0.04 + "s";
      tag.innerHTML = escapeHtml(kw.word) + ' <span class="keyword-tag__count">' + kw.count + "</span>";
      cloud.appendChild(tag);
    });

    // Highlights
    var list = document.getElementById("highlights-list");
    list.innerHTML = "";
    var scores = (data.highlights || []).map(function (h) { return h.score; });
    var maxScore = Math.max.apply(null, scores.concat([1]));
    (data.highlights || []).forEach(function (h, i) {
      var pct = Math.round((h.score / maxScore) * 100);
      var li = document.createElement("li");
      li.className = "highlight-item";
      li.style.animationDelay = i * 0.06 + "s";
      li.innerHTML =
        '<span class="highlight-item__rank">' + (i + 1) + "</span>" +
        '<div class="highlight-item__body">' +
        '<p class="highlight-item__text">' + escapeHtml(h.sentence) + "</p>" +
        '<div class="highlight-item__bar">' +
        '<div class="highlight-item__bar-fill" style="width:' + pct + '%"></div>' +
        "</div></div>";
      list.appendChild(li);
    });

    // Transcript
    document.getElementById("transcript-text").textContent = fullTranscript;
  }

  function escapeHtml(text) {
    var el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
  }

  // ── Copy to clipboard ──────────────────────────────────────
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = document.getElementById(btn.dataset.copy);
      if (!target) return;
      navigator.clipboard.writeText(target.textContent).then(function () {
        showToast("Copied to clipboard");
      });
    });
  });

  // ── Download transcript ─────────────────────────────────────
  downloadBtn.addEventListener("click", function () {
    if (!fullTranscript) return;
    var blob = new Blob([fullTranscript], { type: "text/plain" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "transcript.txt";
    a.click();
    URL.revokeObjectURL(url);
    showToast("Downloading transcript");
  });
})();