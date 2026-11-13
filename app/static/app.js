/* Sada — frontend. Vanilla JS, no build step, no dependencies. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "sada_token";

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: null,
    job: null,
    mode: "login",
    pollTimer: null,
  };

  // ---------- helpers ----------
  const api = async (path, opts = {}) => {
    const headers = { ...(opts.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (opts.body && !(opts.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401 && state.token) {
      signOut();
      throw new Error("Your session expired. Please sign in again.");
    }
    return res;
  };

  const toast = (msg, kind = "info") => {
    const el = $("toast");
    el.textContent = msg;
    el.dataset.kind = kind;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 3600);
  };

  const fmtTime = (s) => {
    const t = Math.max(0, Math.round(s));
    const m = Math.floor(t / 60);
    const sec = t % 60;
    return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };

  const fmtBytes = (b) => {
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
    return `${(b / 1024 / 1024).toFixed(1)} MB`;
  };

  const tierOf = (conf) => (conf >= 0.8 ? "high" : conf >= 0.5 ? "mid" : "low");

  // ---------- auth ----------
  const setAuthUI = () => {
    const btn = $("authBtn");
    if (state.user) {
      btn.textContent = "Sign out";
      btn.onclick = signOut;
      $("heroNote").innerHTML = `Signed in as <strong>${escapeHtml(state.user.email)}</strong>.`;
    } else {
      btn.textContent = "Sign in";
      btn.onclick = () => openAuth("login");
      $("heroNote").innerHTML =
        'No account needed to try it — <button class="linkbtn" id="demoBtn" type="button">use the demo account</button>.';
      const d = $("demoBtn");
      if (d) d.onclick = demoLogin;
    }
  };

  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const openAuth = (mode) => {
    state.mode = mode;
    const isReg = mode === "register";
    $("authTitle").textContent = isReg ? "Create an account" : "Sign in";
    $("authSub").textContent = isReg
      ? "Your files stay private to your account."
      : "Welcome back.";
    $("nameField").hidden = !isReg;
    $("authSubmit").textContent = isReg ? "Create account" : "Sign in";
    $("switchText").textContent = isReg ? "Already have an account?" : "No account yet?";
    $("switchMode").textContent = isReg ? "Sign in" : "Create one";
    $("authPass").autocomplete = isReg ? "new-password" : "current-password";
    $("authError").hidden = true;
    $("authModal").hidden = false;
    setTimeout(() => $("authEmail").focus(), 60);
  };

  const closeAuth = () => { $("authModal").hidden = true; };

  const signOut = () => {
    state.token = "";
    state.user = null;
    localStorage.removeItem(TOKEN_KEY);
    setAuthUI();
    $("history").hidden = true;
    $("workspace").hidden = true;
    toast("Signed out.");
  };

  const demoLogin = async () => {
    try {
      const res = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: "demo@sada.app", password: "demo12345" }),
      });
      if (!res.ok) {
        toast("Demo account is not seeded on this instance.", "error");
        return;
      }
      const data = await res.json();
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      setAuthUI();
      loadHistory();
      toast("Signed in to the demo account.");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  $("authForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("authError");
    err.hidden = true;
    const email = $("authEmail").value.trim();
    const password = $("authPass").value;
    const display_name = $("authName").value.trim();
    const isReg = state.mode === "register";

    if (!email || !password) {
      err.textContent = "Email and password are both required.";
      err.hidden = false;
      return;
    }
    if (isReg && password.length < 8) {
      err.textContent = "Password must be at least 8 characters.";
      err.hidden = false;
      return;
    }

    const btn = $("authSubmit");
    btn.disabled = true;
    btn.textContent = isReg ? "Creating…" : "Signing in…";
    try {
      const res = await api(`/api/auth/${isReg ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify(isReg ? { email, password, display_name } : { email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        err.textContent =
          typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.";
        err.hidden = false;
        return;
      }
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      closeAuth();
      setAuthUI();
      loadHistory();
      toast(isReg ? "Account created." : "Signed in.");
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = isReg ? "Create account" : "Sign in";
    }
  });

  $("authClose").onclick = closeAuth;
  $("authModal").addEventListener("click", (e) => {
    if (e.target === $("authModal")) closeAuth();
  });
  $("switchMode").onclick = () => openAuth(state.mode === "login" ? "register" : "login");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("authModal").hidden) closeAuth();
  });

  // ---------- upload ----------
  const dz = $("dropzone");
  const fileInput = $("fileInput");

  dz.addEventListener("click", () => {
    if (!state.user) { openAuth("login"); return; }
    fileInput.click();
  });
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); dz.click(); }
  });
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
  );
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f) handleFile(f);
  });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) handleFile(f);
    fileInput.value = "";
  });

  const handleFile = (file) => {
    if (!state.user) { openAuth("login"); return; }
    if (file.size > 100 * 1024 * 1024) {
      toast("That file is over the 100 MB limit.", "error");
      return;
    }
    upload(file);
  };

  const upload = (file) => {
    const prog = $("dzProgress");
    const bar = $("dzBar");
    const status = $("dzStatus");
    prog.hidden = false;
    dz.classList.add("busy");
    bar.style.width = "0%";
    status.textContent = `Uploading ${file.name}…`;

    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.setRequestHeader("Authorization", `Bearer ${state.token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        bar.style.width = `${pct}%`;
        status.textContent = pct < 100 ? `Uploading… ${pct}%` : "Queued for transcription…";
      }
    };

    xhr.onload = () => {
      dz.classList.remove("busy");
      if (xhr.status === 202) {
        const job = JSON.parse(xhr.responseText);
        bar.style.width = "100%";
        status.textContent = "Transcribing…";
        watchJob(job.id);
      } else {
        let msg = "Upload failed.";
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* keep default */ }
        prog.hidden = true;
        toast(typeof msg === "string" ? msg : "Upload failed.", "error");
      }
    };
    xhr.onerror = () => {
      dz.classList.remove("busy");
      prog.hidden = true;
      toast("Network error during upload.", "error");
    };
    xhr.send(form);
  };

  // ---------- job polling ----------
  const watchJob = (id) => {
    clearInterval(state.pollTimer);
    let ticks = 0;
    state.pollTimer = setInterval(async () => {
      ticks += 1;
      try {
        const res = await api(`/api/jobs/${id}`);
        if (!res.ok) throw new Error("Could not load the job.");
        const job = await res.json();
        if (job.status === "done") {
          clearInterval(state.pollTimer);
          $("dzProgress").hidden = true;
          renderJob(job);
          loadHistory();
        } else if (job.status === "failed") {
          clearInterval(state.pollTimer);
          $("dzProgress").hidden = true;
          toast(job.error || "Transcription failed.", "error");
          loadHistory();
        } else if (ticks > 300) {
          clearInterval(state.pollTimer);
          $("dzProgress").hidden = true;
          toast("This is taking longer than expected. Check back later.", "error");
        }
      } catch (e) {
        clearInterval(state.pollTimer);
        $("dzProgress").hidden = true;
        toast(e.message, "error");
      }
    }, 1200);
  };

  // ---------- render ----------
  const renderJob = (job) => {
    state.job = job;
    $("workspace").hidden = false;
    $("wsTitle").textContent = job.original_filename;
    $("wsMeta").textContent = [
      job.language ? `${job.language.toUpperCase()} ${(job.language_probability * 100).toFixed(0)}%` : null,
      job.duration_seconds ? fmtTime(job.duration_seconds) : null,
      fmtBytes(job.size_bytes),
      job.model_name ? `whisper-${job.model_name}` : null,
    ].filter(Boolean).join("  ·  ");

    // confidence bar
    const bar = $("confBar");
    const fill = $("confFill");
    const label = $("confLabel");
    bar.hidden = false;
    const pct = Math.round(job.confidence * 100);
    fill.style.width = `${pct}%`;
    fill.style.background =
      pct >= 80 ? "linear-gradient(90deg,#22c55e,#4ade80)"
      : pct >= 50 ? "linear-gradient(90deg,#d97706,#fbbf24)"
      : "linear-gradient(90deg,#dc2626,#f87171)";
    const flagged = job.uncertain_count;
    label.textContent = flagged
      ? `${pct}% overall confidence · ${flagged} line${flagged === 1 ? "" : "s"} flagged for review`
      : `${pct}% overall confidence · nothing flagged`;

    // segments
    const box = $("transcript");
    box.innerHTML = "";
    if (!job.segments.length) {
      box.innerHTML = '<p class="empty">No speech was detected in this file.</p>';
    } else {
      const frag = document.createDocumentFragment();
      job.segments.forEach((s) => {
        const tier = tierOf(s.confidence);
        const row = document.createElement("div");
        row.className = "seg";
        row.dataset.tier = tier;

        const time = document.createElement("span");
        time.className = "seg-time";
        time.textContent = fmtTime(s.start);

        const text = document.createElement("span");
        text.className = "seg-text";
        text.textContent = s.text;

        // Meta goes in its own block so the badge and the doubted words land
        // in the same place on every line, whether or not the text wraps.
        // The badge follows the server's `uncertain` flag, not the colour tier
        // — otherwise the header count and the badges disagree.
        if (s.uncertain || s.low_words) {
          const meta = document.createElement("span");
          meta.className = "seg-meta";

          if (s.uncertain) {
            const flag = document.createElement("span");
            flag.className = "seg-flag";
            flag.textContent = tier === "low" ? "check" : "unsure";
            meta.appendChild(flag);

            const conf = document.createElement("span");
            conf.className = "seg-conf";
            conf.textContent = `${Math.round(s.confidence * 100)}%`;
            meta.appendChild(conf);
          }

          // Name the actual words the model doubted — that is the whole point.
          // A line can have a doubtful word without being flagged for review
          // (the rest of it was solid), so label that case differently rather
          // than leaving a bare "doubted:" with no badge next to it.
          if (s.low_words) {
            const words = document.createElement("span");
            words.className = "seg-words";
            words.textContent = s.uncertain
              ? `doubted: ${s.low_words}`
              : `one word unsure: ${s.low_words}`;
            meta.appendChild(words);
          }

          text.appendChild(meta);
        }

        row.append(time, text);
        frag.appendChild(row);
      });
      box.appendChild(frag);
    }

    $("workspace").scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ---------- export ----------
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", async () => {
      if (!state.job) return;
      const fmt = chip.dataset.fmt;
      try {
        const res = await api(`/api/jobs/${state.job.id}/export?fmt=${fmt}`);
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          toast(typeof d.detail === "string" ? d.detail : "Export failed.", "error");
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${state.job.original_filename.replace(/\.[^.]+$/, "")}.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        toast(`Downloaded .${fmt}`);
      } catch (e) {
        toast(e.message, "error");
      }
    });
  });

  $("copyBtn").onclick = async () => {
    if (!state.job) return;
    try {
      await navigator.clipboard.writeText(state.job.full_text || "");
      toast("Transcript copied.");
    } catch {
      toast("Could not access the clipboard.", "error");
    }
  };

  $("newBtn").onclick = () => {
    $("workspace").hidden = true;
    state.job = null;
    $("upload").scrollIntoView({ behavior: "smooth", block: "start" });
  };

  $("deleteBtn").onclick = async () => {
    if (!state.job) return;
    if (!confirm("Delete this file and its transcript? This cannot be undone.")) return;
    try {
      const res = await api(`/api/jobs/${state.job.id}`, { method: "DELETE" });
      if (res.status === 204) {
        $("workspace").hidden = true;
        state.job = null;
        loadHistory();
        toast("Deleted.");
      } else {
        toast("Could not delete that file.", "error");
      }
    } catch (e) {
      toast(e.message, "error");
    }
  };

  // ---------- history ----------
  const loadHistory = async () => {
    if (!state.user) return;
    try {
      const res = await api("/api/jobs?limit=20");
      if (!res.ok) return;
      const data = await res.json();
      const sec = $("history");
      const list = $("jobList");
      if (!data.items.length) {
        sec.hidden = true;
        return;
      }
      sec.hidden = false;
      list.innerHTML = "";
      data.items.forEach((j) => {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "job-item";

        const wrap = document.createElement("div");
        wrap.className = "job-name";
        wrap.textContent = j.original_filename;
        const sub = document.createElement("div");
        sub.className = "job-sub";
        sub.textContent = [
          j.duration_seconds ? fmtTime(j.duration_seconds) : null,
          j.status === "done" ? `${Math.round(j.confidence * 100)}% conf` : null,
          new Date(j.created_at).toLocaleDateString(),
        ].filter(Boolean).join(" · ");
        wrap.appendChild(sub);

        const badge = document.createElement("span");
        badge.className = "job-badge";
        badge.dataset.s = j.status;
        badge.textContent = j.status;

        btn.append(wrap, badge);
        btn.onclick = async () => {
          if (j.status !== "done") {
            toast(`That file is ${j.status}.`, "error");
            return;
          }
          const r = await api(`/api/jobs/${j.id}`);
          if (r.ok) renderJob(await r.json());
        };
        li.appendChild(btn);
        list.appendChild(li);
      });
    } catch { /* history is a nicety; never block the page on it */ }
  };

  // ---------- boot ----------
  const boot = async () => {
    setAuthUI();
    if (!state.token) return;
    try {
      const res = await api("/api/auth/me");
      if (res.ok) {
        state.user = await res.json();
        setAuthUI();
        loadHistory();
      } else {
        signOut();
      }
    } catch {
      signOut();
    }
  };

  boot();
})();
