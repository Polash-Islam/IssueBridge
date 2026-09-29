document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector("#sidebar");
  document.querySelector("#menuToggle")?.addEventListener("click", () => sidebar?.classList.toggle("open"));

  document.querySelectorAll(".alert button").forEach((button) => {
    button.addEventListener("click", () => button.closest(".alert")?.remove());
  });

  const uploadZone = document.querySelector("#uploadZone");
  const uploadInput = uploadZone?.querySelector("input[type=file]");
  const preview = document.querySelector("#filePreview");
  if (uploadZone && uploadInput && preview) {
    ["dragenter", "dragover"].forEach((eventName) => uploadZone.addEventListener(eventName, () => uploadZone.classList.add("dragging")));
    ["dragleave", "drop"].forEach((eventName) => uploadZone.addEventListener(eventName, () => uploadZone.classList.remove("dragging")));
    uploadInput.addEventListener("change", () => {
      preview.innerHTML = "";
      [...uploadInput.files].forEach((file) => {
        const item = document.createElement("span");
        item.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
        preview.appendChild(item);
      });
    });
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      document.querySelector(".global-search input")?.focus();
    }
  });

  const passwordToggle = document.querySelector(".password-toggle");
  passwordToggle?.addEventListener("click", () => {
    const input = document.querySelector("#id_password");
    if (!input) return;
    input.type = input.type === "password" ? "text" : "password";
    passwordToggle.textContent = input.type === "password" ? "Show" : "Hide";
  });

  const board = document.querySelector(".kanban-board");
  if (board) {
    let dragged = null;
    const toast = document.querySelector("#boardToast");
    const showToast = (message, isError = false) => {
      toast.textContent = message;
      toast.classList.toggle("error", isError);
      toast.classList.add("show");
      window.setTimeout(() => toast.classList.remove("show"), 2600);
    };
    document.querySelectorAll(".kanban-card[draggable=true]").forEach((card) => {
      card.addEventListener("dragstart", () => {
        dragged = card;
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("dragging");
        document.querySelectorAll(".kanban-dropzone").forEach((zone) => zone.classList.remove("drag-over"));
      });
    });
    document.querySelectorAll(".kanban-column").forEach((column) => {
      const zone = column.querySelector(".kanban-dropzone");
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("drag-over");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
      zone.addEventListener("drop", async (event) => {
        event.preventDefault();
        zone.classList.remove("drag-over");
        if (!dragged) return;
        const target = column.dataset.status;
        const allowed = (dragged.dataset.allowed || "").split(",").filter(Boolean);
        if (!allowed.includes(target)) {
          showToast("That move requires a review, assignment, verification, or approved transition.", true);
          return;
        }
        const sendMove = async (comment = "") => {
          const body = new URLSearchParams({ticket: dragged.dataset.ticket, to_status: target, comment});
          return fetch(board.dataset.moveUrl, {
            method: "POST",
            headers: {"X-CSRFToken": document.querySelector(".csrf-provider input").value, "Content-Type": "application/x-www-form-urlencoded"},
            body,
          });
        };
        let response = await sendMove();
        let result = await response.json();
        if (!response.ok && result.requires_comment) {
          const reason = window.prompt("This workflow step requires a progress note or reason:");
          if (!reason) return;
          response = await sendMove(reason);
          result = await response.json();
        }
        if (!response.ok) {
          showToast(result.error || "The ticket could not be moved.", true);
          return;
        }
        zone.prepend(dragged);
        dragged.dataset.status = result.status_code;
        showToast(`${dragged.dataset.ticket} moved to ${result.status}.`);
        window.setTimeout(() => window.location.reload(), 500);
      });
    });
  }
});
