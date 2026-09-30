(function () {
  const table = document.getElementById("documents");
  if (!table) return;
  const applicationId = table.dataset.applicationId;
  const FIELDS = ["document_status", "date_received", "expiration_date", "notes"];

  function fieldEl(row, field) {
    return row.querySelector('[data-field="' + field + '"]');
  }

  function currentValues(row) {
    const values = {};
    FIELDS.forEach(function (f) { values[f] = fieldEl(row, f).value; });
    return values;
  }

  function saved(row) {
    return JSON.parse(row.dataset.saved);
  }

  function changedFields(row) {
    const original = saved(row);
    const now = currentValues(row);
    return FIELDS.filter(function (f) { return now[f] !== original[f]; });
  }

  function setMessage(row, text, isError) {
    const el = row.querySelector(".save-message");
    el.textContent = text;
    el.classList.toggle("save-error", Boolean(isError));
  }

  function refreshDirty(row) {
    const dirty = changedFields(row).length > 0;
    row.classList.toggle("row-dirty", dirty);
    row.querySelector(".row-actions").hidden = !dirty;
    if (dirty) setMessage(row, "Unsaved changes", false);
  }

  function applyDocument(row, doc) {
    FIELDS.forEach(function (f) { fieldEl(row, f).value = doc[f]; });
    row.dataset.saved = JSON.stringify(currentValues(row));
    row.querySelector(".expiration-text").textContent = doc.expiration_text;
    const badge = row.querySelector(".state-badge");
    badge.className = "badge state-badge" + (doc.state ? " badge-" + doc.state : "");
    badge.textContent = doc.state_label;
    badge.hidden = !doc.state;
  }

  function applySummary(summary) {
    document.getElementById("sum-outstanding").textContent = summary.outstanding_count;
    document.getElementById("sum-expired").textContent = summary.expired_count;
    document.getElementById("sum-expiring").textContent = summary.expiring_soon_count;
    document.getElementById("sum-severity").textContent = summary.severity_score;
    document.getElementById("stalled-badge").hidden = !summary.is_stalled;
  }

  async function save(row) {
    const fields = changedFields(row);
    if (fields.length === 0) return;
    const now = currentValues(row);
    const body = {};
    fields.forEach(function (f) {
      body[f] = now[f] === "" && f !== "notes" ? null : now[f];
    });
    const saveButton = row.querySelector(".row-save");
    saveButton.disabled = true;
    setMessage(row, "Saving...", false);
    try {
      const response = await fetch(
        "/applications/" + encodeURIComponent(applicationId) + "/documents/" + row.dataset.documentId,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      applyDocument(row, data.document);
      applySummary(data.summary);
      document.getElementById("sum-activity").textContent = data.activity_text;
      row.classList.remove("row-dirty");
      row.querySelector(".row-actions").hidden = true;
      setMessage(row, "Saved", false);
    } catch (err) {
      setMessage(row, "Could not save - your changes are still here, please try again", true);
    } finally {
      saveButton.disabled = false;
    }
  }

  function cancel(row) {
    const original = saved(row);
    FIELDS.forEach(function (f) { fieldEl(row, f).value = original[f]; });
    row.classList.remove("row-dirty");
    row.querySelector(".row-actions").hidden = true;
    setMessage(row, "", false);
  }

  table.querySelectorAll("tbody tr").forEach(function (row) {
    row.dataset.saved = JSON.stringify(currentValues(row));
  });

  function onEdit(event) {
    if (!event.target.closest("[data-field]")) return;
    refreshDirty(event.target.closest("tr"));
  }
  table.addEventListener("input", onEdit);
  table.addEventListener("change", onEdit);

  table.addEventListener("click", function (event) {
    const row = event.target.closest("tr");
    if (event.target.closest(".row-save")) save(row);
    if (event.target.closest(".row-cancel")) cancel(row);
  });

  table.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.matches('input[data-field="notes"]')) {
      event.preventDefault();
      save(event.target.closest("tr"));
    }
  });
})();
