// StudyMate AI — frontend logic
// Talks to the Flask backend endpoints: /api/upload, /api/notes, /api/search,
// /api/ask, /api/tts, /api/stt

(function () {
  "use strict";

  // ---------- Tabs ----------
  const tabButtons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".panel");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`panel-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "library") loadNotes();
    });
  });

  // ---------- Upload / Capture ----------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const dropzoneText = document.getElementById("dropzoneText");
  const uploadBtn = document.getElementById("uploadBtn");
  const uploadHint = document.getElementById("uploadHint");
  const resultCard = document.getElementById("resultCard");
  const resultFilename = document.getElementById("resultFilename");
  const resultSummary = document.getElementById("resultSummary");
  const resultKeyphrases = document.getElementById("resultKeyphrases");
  const resultText = document.getElementById("resultText");
  const toggleTextBtn = document.getElementById("toggleTextBtn");
  const listenBtn = document.getElementById("listenBtn");
  const audioPlayer = document.getElementById("audioPlayer");

  let selectedFile = null;
  let lastSummary = "";

  ["dragover", "dragenter"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelected(file);
  });
  fileInput.addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileSelected(e.target.files[0]);
  });

  function handleFileSelected(file) {
    selectedFile = file;
    dropzoneText.textContent = file.name;
    uploadBtn.disabled = false;
    uploadHint.textContent = "";
    uploadHint.classList.remove("error");
  }

  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    uploadBtn.disabled = true;
    uploadHint.classList.remove("error");
    uploadHint.textContent = "Reading text, analyzing, and summarizing…";
    resultCard.hidden = true;

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();

      if (!res.ok) {
        uploadHint.textContent = data.error || "Something went wrong.";
        uploadHint.classList.add("error");
        uploadBtn.disabled = false;
        return;
      }

      lastSummary = data.summary;
      resultFilename.textContent = data.filename;
      resultSummary.textContent = data.summary;
      resultKeyphrases.innerHTML = "";
      (data.key_phrases || []).forEach((kp) => {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = kp;
        resultKeyphrases.appendChild(tag);
      });
      resultText.textContent = data.extracted_text;
      resultText.hidden = true;
      toggleTextBtn.textContent = "Show extracted text";
      audioPlayer.hidden = true;
      resultCard.hidden = false;

      uploadHint.textContent = "Done — saved to your library.";
      uploadBtn.disabled = false;
    } catch (err) {
      uploadHint.textContent = "Network error: " + err.message;
      uploadHint.classList.add("error");
      uploadBtn.disabled = false;
    }
  });

  toggleTextBtn.addEventListener("click", () => {
    resultText.hidden = !resultText.hidden;
    toggleTextBtn.textContent = resultText.hidden ? "Show extracted text" : "Hide extracted text";
  });

  listenBtn.addEventListener("click", () => speakText(lastSummary, listenBtn, audioPlayer));

  async function speakText(text, triggerBtn, playerEl) {
    if (!text) return;
    const originalLabel = triggerBtn.textContent;
    triggerBtn.textContent = "Synthesizing…";
    triggerBtn.disabled = true;
    try {
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.error || "Could not synthesize audio.");
        return;
      }
      const blob = await res.blob();
      playerEl.src = URL.createObjectURL(blob);
      playerEl.hidden = false;
      playerEl.play();
    } catch (err) {
      alert("Network error: " + err.message);
    } finally {
      triggerBtn.textContent = originalLabel;
      triggerBtn.disabled = false;
    }
  }

  // ---------- Library ----------
  const notesGrid = document.getElementById("notesGrid");
  const searchInput = document.getElementById("searchInput");
  const searchBtn = document.getElementById("searchBtn");

  async function loadNotes() {
    notesGrid.innerHTML = `<p class="empty-state">Loading your notes…</p>`;
    try {
      const res = await fetch("/api/notes");
      const data = await res.json();
      if (!res.ok) {
        notesGrid.innerHTML = `<p class="empty-state">${data.error || "Could not load notes."}</p>`;
        return;
      }
      renderNotes(data.notes || []);
    } catch (err) {
      notesGrid.innerHTML = `<p class="empty-state">Network error: ${err.message}</p>`;
    }
  }

  function renderNotes(notes) {
    if (!notes.length) {
      notesGrid.innerHTML = `<p class="empty-state">No notes yet — head to <strong>Capture</strong> to upload your first page.</p>`;
      return;
    }
    notesGrid.innerHTML = "";
    notes.forEach((n) => {
      const card = document.createElement("div");
      card.className = "note-card";
      const date = n.uploaded_at ? new Date(n.uploaded_at).toLocaleString() : "";
      card.innerHTML = `
        <p class="note-name">${escapeHtml(n.filename || "note")}</p>
        <p class="note-summary">${escapeHtml(n.summary || "")}</p>
        <p class="note-date">${date}</p>
      `;
      notesGrid.appendChild(card);
    });
  }

  searchBtn.addEventListener("click", runSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });

  async function runSearch() {
    const query = searchInput.value.trim();
    if (!query) return loadNotes();
    notesGrid.innerHTML = `<p class="empty-state">Searching…</p>`;
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      if (!res.ok) {
        notesGrid.innerHTML = `<p class="empty-state">${data.error || "Search failed."}</p>`;
        return;
      }
      renderNotes(data.results || []);
    } catch (err) {
      notesGrid.innerHTML = `<p class="empty-state">Network error: ${err.message}</p>`;
    }
  }

  // ---------- Ask ----------
  const chatLog = document.getElementById("chatLog");
  const questionInput = document.getElementById("questionInput");
  const askBtn = document.getElementById("askBtn");
  const askHint = document.getElementById("askHint");
  const micBtn = document.getElementById("micBtn");

  askBtn.addEventListener("click", submitQuestion);
  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitQuestion();
  });

  function addBubble(role, text, sources) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;
    if (sources && sources.length) {
      const src = document.createElement("span");
      src.className = "sources";
      src.textContent = "From: " + sources.join(", ");
      bubble.appendChild(src);
    }
    chatLog.appendChild(bubble);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  async function submitQuestion() {
    const question = questionInput.value.trim();
    if (!question) return;
    addBubble("user", question);
    questionInput.value = "";
    askHint.textContent = "Thinking through your notes…";

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      askHint.textContent = "";
      if (!res.ok) {
        addBubble("assistant", data.error || "Something went wrong.");
        return;
      }
      addBubble("assistant", data.answer, data.sources);
    } catch (err) {
      askHint.textContent = "";
      addBubble("assistant", "Network error: " + err.message);
    }
  }

  // ---------- Voice question (speech-to-text) ----------
  let mediaRecorder = null;
  let audioChunks = [];
  let isRecording = false;

  micBtn.addEventListener("click", async () => {
    if (!isRecording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = handleRecordingStop;
        mediaRecorder.start();
        isRecording = true;
        micBtn.classList.add("recording");
        askHint.textContent = "Listening… click the mic again to stop.";
      } catch (err) {
        askHint.textContent = "Microphone access denied or unavailable.";
        askHint.classList.add("error");
      }
    } else {
      mediaRecorder.stop();
      isRecording = false;
      micBtn.classList.remove("recording");
    }
  });

  async function handleRecordingStop() {
    askHint.textContent = "Transcribing…";
    const blob = new Blob(audioChunks, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "question.webm");

    try {
      const res = await fetch("/api/stt", { method: "POST", body: formData });
      const data = await res.json();
      askHint.textContent = "";
      if (!res.ok) {
        askHint.textContent = data.error || "Could not transcribe audio.";
        askHint.classList.add("error");
        return;
      }
      questionInput.value = data.text;
      submitQuestion();
    } catch (err) {
      askHint.textContent = "Network error: " + err.message;
      askHint.classList.add("error");
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Initial load
  loadNotes();
})();
