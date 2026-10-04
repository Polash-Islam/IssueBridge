document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-status-color]").forEach((element) => {
    element.style.setProperty("--badge", element.dataset.statusColor);
  });
  document.querySelectorAll("[data-priority-color]").forEach((element) => {
    element.style.backgroundColor = element.dataset.priorityColor;
  });

  const activityDialog = document.querySelector("#activityDialog");
  let activityTrigger;
  if (activityDialog) {
    document.querySelectorAll('[data-activity-target]').forEach(trigger => {
      const open = () => {
        activityDialog.querySelectorAll('.activity-detail').forEach(detail => {
          detail.hidden = detail.id !== trigger.dataset.activityTarget;
        });
        activityTrigger = trigger;
        if (!activityDialog.open) activityDialog.showModal();
        activityDialog.scrollTop = 0;
      };
      trigger.addEventListener('click', event => {
        if (!event.target.closest('a')) open();
      });
      trigger.addEventListener('keydown', event => {
        if (event.target === trigger && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          open();
        }
      });
    });
    activityDialog.addEventListener("click", (event) => {
      const bounds = activityDialog.getBoundingClientRect();
      if (event.target === activityDialog && (
        event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom
      )) activityDialog.close();
    });
    activityDialog.addEventListener("close", () => activityTrigger?.focus());
  }
  const sidebar = document.querySelector("#sidebar");
  document.querySelector("#menuToggle")?.addEventListener("click", () => sidebar?.classList.toggle("open"));

  document.querySelectorAll(".field select[multiple]").forEach((select) => {
    const container = document.createElement("div");
    container.className = "multi-select";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "form-control multi-select-toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", `${select.id}-options`);
    const menu = document.createElement("div");
    menu.className = "multi-select-menu";
    menu.id = `${select.id}-options`;
    menu.setAttribute("role", "group");
    const fieldLabel = select.closest(".field")?.querySelector("label")?.textContent.trim() || "Options";
    menu.setAttribute("aria-label", fieldLabel);

    [...select.options].forEach((option) => {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = option.selected;
      checkbox.addEventListener("change", () => {
        option.selected = checkbox.checked;
        select.dispatchEvent(new Event("change", {bubbles: true}));
      });
      label.append(checkbox, document.createTextNode(option.text));
      menu.appendChild(label);
    });

    const updateToggle = () => {
      const selected = [...select.selectedOptions];
      toggle.textContent = selected.length === 1 ? selected[0].text :
        selected.length ? `${selected.length} selected` : "Select participants";
      toggle.setAttribute("aria-label", `${fieldLabel}: ${selected.length} selected`);
      menu.querySelectorAll("input[type=checkbox]").forEach((checkbox, index) => {
        checkbox.checked = select.options[index].selected;
      });
    };
    toggle.addEventListener("click", () => {
      const isOpen = container.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
    select.addEventListener("change", updateToggle);
    select.form?.addEventListener("reset", () => window.setTimeout(updateToggle));
    document.addEventListener("click", (event) => {
      if (!container.contains(event.target)) {
        container.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && container.classList.contains("is-open")) {
        container.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });

    select.parentNode.insertBefore(container, select);
    container.append(toggle, menu, select);
    select.classList.add("multi-select-native");
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    updateToggle();
  });

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
      if (uploadInput.files.length) {
        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.className = "btn btn-secondary btn-small";
        clearButton.textContent = "Clear";
        clearButton.setAttribute("aria-label", "Clear selected attachments");
        clearButton.addEventListener("click", () => {
          uploadInput.value = "";
          uploadInput.dispatchEvent(new Event("change", { bubbles: true }));
          uploadInput.focus();
        });
        preview.appendChild(clearButton);
      }
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
