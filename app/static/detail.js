(function () {
  const table = document.getElementById("documents");
  if (!table) return;
  const applicationId = table.dataset.applicationId;

  function setMessage(row, text, isError) {
    const el = row.querySelector(".save-message");
    el.textContent = text;
    el.classList.toggle("save-error", Boolean(isError));
  }

  function applyDocument(row, doc) {
    row.querySelector('[data-field="document_status"]').value = doc.document_status;
    row.querySelector('[data-field="date_received"]').value = doc.date_received;
    row.querySelector('[data-field="expiration_date"]').value = doc.expiration_date;
    row.querySelector('[data-field="notes"]').value = doc.notes;
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

  async function save(row, field, value) {
    setMessage(row, "Saving...", false);
    try {
      const response = await fetch(
        "/applications/" + encodeURIComponent(applicationId) + "/documents/" + row.dataset.documentId,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: value }),
        }
      );
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      applyDocument(row, data.document);
      applySummary(data.summary);
      document.getElementById("sum-activity").textContent = data.activity_text;
      setMessage(row, "Saved", false);
    } catch (err) {
      setMessage(row, "Could not save - please try again", true);
    }
  }

  table.addEventListener("change", function (event) {
    const input = event.target.closest("[data-field]");
    if (!input) return;
    const row = input.closest("tr");
    const field = input.dataset.field;
    const value = input.value === "" && field !== "notes" ? null : input.value;
    save(row, field, value);
  });
})();
