(() => {
  const resumeText = document.getElementById("resume-text");
  const resumeFile = document.getElementById("resume-file");
  const jdText = document.getElementById("jd-text");
  const jdFile = document.getElementById("jd-file");
  const submitBtn = document.getElementById("submit-btn");
  const statusEl = document.getElementById("status");
  const results = document.getElementById("results");
  const formattedOutput = document.getElementById("formatted-output");
  const keywordsIn = document.getElementById("keywords-in");
  const keywordsOut = document.getElementById("keywords-out");
  const needsInput = document.getElementById("needs-input");
  const changesList = document.getElementById("changes-list");
  const copyBtn = document.getElementById("copy-btn");

  function setStatus(msg, kind = "") {
    statusEl.textContent = msg;
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function addChip(list, text) {
    const li = document.createElement("li");
    li.textContent = text;
    list.appendChild(li);
  }

  function renderResult(data) {
    formattedOutput.textContent = data.formatted_resume || "";

    clearChildren(keywordsIn);
    (data.keywords_incorporated || []).forEach((k) => addChip(keywordsIn, k));

    clearChildren(keywordsOut);
    (data.keywords_skipped || []).forEach((k) => addChip(keywordsOut, k));

    clearChildren(needsInput);
    (data.needs_user_input || []).forEach((item) => {
      const li = document.createElement("li");
      const loc = document.createElement("strong");
      loc.textContent = item.location;
      const text = document.createTextNode(item.suggestion);
      li.appendChild(loc);
      li.appendChild(text);
      needsInput.appendChild(li);
    });

    clearChildren(changesList);
    (data.changes || []).forEach((ch) => {
      const box = document.createElement("div");
      box.className = "change-item";

      const meta = document.createElement("div");
      meta.className = "meta";
      const section = document.createElement("span");
      section.className = "section";
      section.textContent = ch.section;
      const type = document.createElement("span");
      type.className = "type";
      type.textContent = (ch.change_type || "").replace(/_/g, " ");
      meta.appendChild(section);
      meta.appendChild(type);
      box.appendChild(meta);

      const diff = document.createElement("div");
      diff.className = "diff";
      const before = document.createElement("div");
      before.className = "before";
      before.textContent = ch.before || "N/A";
      const after = document.createElement("div");
      after.className = "after";
      after.textContent = ch.after || "";
      diff.appendChild(before);
      diff.appendChild(after);
      box.appendChild(diff);

      if (ch.rationale) {
        const rationale = document.createElement("div");
        rationale.className = "rationale";
        rationale.textContent = ch.rationale;
        box.appendChild(rationale);
      }

      changesList.appendChild(box);
    });

    results.classList.remove("hidden");
  }

  async function readFileAsText(file) {
    if (!file) return "";
    if (file.name.toLowerCase().endsWith(".txt")) {
      return await file.text();
    }
    return "";
  }

  resumeFile.addEventListener("change", async () => {
    const f = resumeFile.files[0];
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".txt")) {
      resumeText.value = await readFileAsText(f);
    } else {
      setStatus(`Selected ${f.name} — will be parsed on submit.`);
    }
  });

  jdFile.addEventListener("change", async () => {
    const f = jdFile.files[0];
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".txt")) {
      jdText.value = await readFileAsText(f);
    } else {
      setStatus(`Selected ${f.name} — will be parsed on submit.`);
    }
  });

  submitBtn.addEventListener("click", async () => {
    const resume = resumeText.value.trim();
    const jd = jdText.value.trim();
    const rFile = resumeFile.files[0];
    const jFile = jdFile.files[0];

    if (!resume && !rFile) {
      setStatus("Please paste or upload your resume.", "error");
      return;
    }
    if (!jd && !jFile) {
      setStatus("Please paste or upload a job description.", "error");
      return;
    }

    submitBtn.disabled = true;
    setStatus("Formatting… this usually takes 20-40 seconds.");

    const form = new FormData();
    if (resume) form.append("resume_text", resume);
    if (jd) form.append("jd_text", jd);
    if (!resume && rFile) form.append("resume_file", rFile);
    if (!jd && jFile) form.append("jd_file", jFile);

    try {
      const resp = await fetch("/api/format", { method: "POST", body: form });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.error || `Request failed (${resp.status}).`, "error");
        return;
      }
      renderResult(data);
      setStatus("Done.", "success");
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setStatus(`Network error: ${err.message}`, "error");
    } finally {
      submitBtn.disabled = false;
    }
  });

  copyBtn.addEventListener("click", async () => {
    const text = formattedOutput.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const original = copyBtn.textContent;
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = original), 1500);
    } catch {
      setStatus("Copy failed — select the text manually.", "error");
    }
  });
})();
