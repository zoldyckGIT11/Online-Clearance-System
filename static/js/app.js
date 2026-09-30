document.addEventListener("DOMContentLoaded", () => {
  const proofDialog = document.querySelector("[data-proof-dialog]");
  if (proofDialog) {
    const proofContent = proofDialog.querySelector("[data-proof-content]");
    const closeProof = proofDialog.querySelector("[data-proof-close]");

    document.querySelectorAll("[data-proof-url]").forEach((button) => {
      button.addEventListener("click", () => {
        const proofUrl = button.dataset.proofUrl;
        const extension = button.dataset.proofType;
        proofContent.replaceChildren();

        if (["jpg", "jpeg", "png"].includes(extension)) {
          const image = document.createElement("img");
          image.className = "proof-image";
          image.src = proofUrl;
          image.alt = "Uploaded clearance proof";
          proofContent.append(image);
        } else {
          const frame = document.createElement("iframe");
          frame.className = "proof-frame";
          frame.title = "Uploaded clearance proof";
          frame.src = extension === "pdf" ? `${proofUrl}#view=FitH` : proofUrl;
          proofContent.append(frame);
        }
        proofDialog.showModal();
      });
    });
    closeProof.addEventListener("click", () => proofDialog.close());
    proofDialog.addEventListener("close", () => {
      proofContent.replaceChildren();
    });
  }

  const confirmationDialog = document.querySelector("[data-confirm-dialog]");
  if (confirmationDialog) {
    const confirmationTitle = confirmationDialog.querySelector(
      "[data-confirm-title]",
    );
    const confirmationDetail = confirmationDialog.querySelector(
      "[data-confirm-detail]",
    );
    const cancelConfirmation = confirmationDialog.querySelector(
      "[data-confirm-cancel]",
    );
    const submitConfirmation = confirmationDialog.querySelector(
      "[data-confirm-submit]",
    );
    let pendingForm;

    document.querySelectorAll("[data-confirm-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (form.dataset.confirmed === "true") {
          delete form.dataset.confirmed;
          return;
        }
        event.preventDefault();
        pendingForm = form;
        confirmationTitle.textContent = form.dataset.confirmTitle;
        confirmationDetail.textContent = form.dataset.confirmDetail;
        confirmationDialog.showModal();
      });
    });

    cancelConfirmation.addEventListener("click", () => {
      confirmationDialog.close();
      pendingForm = null;
    });
    submitConfirmation.addEventListener("click", () => {
      if (!pendingForm) return;
      const form = pendingForm;
      pendingForm = null;
      confirmationDialog.close();
      form.dataset.confirmed = "true";
      form.requestSubmit();
    });
    confirmationDialog.addEventListener("close", () => {
      pendingForm = null;
    });
  }

  const profilePhotoInput = document.querySelector(
    "[data-profile-photo-input]",
  );
  const profilePhotoHolder = document.querySelector(".profile-photo-holder");
  if (profilePhotoInput && profilePhotoHolder) {
    const uploadButton = document.querySelector("[data-profile-photo-upload]");
    let previewUrl;
    profilePhotoInput.addEventListener("change", () => {
      const file = profilePhotoInput.files[0];
      const hasValidImage = Boolean(file && file.type.startsWith("image/"));
      if (uploadButton) uploadButton.hidden = !hasValidImage;
      if (!hasValidImage) return;

      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(file);
      let image = profilePhotoHolder.querySelector(".profile-photo");
      if (!image) {
        image = document.createElement("img");
        image.className = "profile-photo";
        image.alt = "Selected profile photo preview";
        profilePhotoHolder.insertBefore(
          image,
          profilePhotoHolder.querySelector(".profile-photo-edit"),
        );
        profilePhotoHolder
          .querySelector(".profile-photo-placeholder")
          ?.remove();
      }
      image.src = previewUrl;
    });
  }

  document.querySelectorAll("[data-profile-edit-form]").forEach((form) => {
    const editButton = form.querySelector("[data-profile-edit]");
    const cancelButton = form.querySelector("[data-profile-cancel]");
    const actions = form.querySelector("[data-profile-edit-actions]");
    const editableFields = Array.from(
      form.querySelectorAll("[data-profile-editable]"),
    );
    const originalValues = editableFields.map((field) => field.value);

    const setEditing = (editing) => {
      editableFields.forEach((field) => {
        field.readOnly = !editing;
      });
      editButton.hidden = editing;
      actions.hidden = !editing;
    };

    editButton.addEventListener("click", () => {
      setEditing(true);
      editableFields[0]?.focus();
    });
    cancelButton.addEventListener("click", () => {
      editableFields.forEach((field, index) => {
        field.value = originalValues[index];
      });
      setEditing(false);
    });
  });

  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    const showIcon = button.querySelector("[data-password-show-icon]");
    const hideIcon = button.querySelector("[data-password-hide-icon]");
    if (!input) return;

    button.addEventListener("click", () => {
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      showIcon.hidden = visible;
      hideIcon.hidden = !visible;
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute(
        "aria-label",
        `${visible ? "Hide" : "Show"} password`,
      );
      button.setAttribute("title", `${visible ? "Hide" : "Show"} password`);
    });
  });

  const applicantTabList = document.querySelector("[data-applicant-tabs]");
  if (applicantTabList) {
    const applicantTabs = Array.from(
      applicantTabList.querySelectorAll("[data-applicant-tab]"),
    );

    const activateApplicantTab = (selectedTab, moveFocus = false) => {
      applicantTabs.forEach((tab) => {
        const isSelected = tab === selectedTab;
        tab.setAttribute("aria-selected", String(isSelected));
        tab.tabIndex = isSelected ? 0 : -1;
        const panel = document.getElementById(
          tab.getAttribute("aria-controls"),
        );
        panel?.classList.toggle("is-hidden", !isSelected);
      });
      if (moveFocus) selectedTab.focus();
    };

    applicantTabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activateApplicantTab(tab));
      tab.addEventListener("keydown", (event) => {
        let nextIndex;
        if (event.key === "ArrowRight") {
          nextIndex = (index + 1) % applicantTabs.length;
        } else if (event.key === "ArrowLeft") {
          nextIndex = (index - 1 + applicantTabs.length) % applicantTabs.length;
        } else if (event.key === "Home") {
          nextIndex = 0;
        } else if (event.key === "End") {
          nextIndex = applicantTabs.length - 1;
        } else {
          return;
        }
        event.preventDefault();
        activateApplicantTab(applicantTabs[nextIndex], true);
      });
    });
  }

  const landingSections = document.querySelectorAll(
    ".landing-page .landing-section, .landing-page .school-background, .landing-page .landing-cta",
  );
  if (landingSections.length) {
    document
      .querySelectorAll(
        ".landing-page .section-intro h2, .landing-page .section-intro p, .landing-page .school-background h2, .landing-page .school-background p",
      )
      .forEach((element) => {
        const words = element.textContent.trim().split(/\s+/);
        element.replaceChildren(
          ...words.map((word, index) => {
            const span = document.createElement("span");
            span.className = "landing-word";
            span.textContent = word;
            span.style.setProperty("--word-index", index);
            return span;
          }),
        );
      });

    const revealSections = (entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    };
    const observer = new IntersectionObserver(revealSections, {
      threshold: 0.15,
    });
    landingSections.forEach((section) => observer.observe(section));
  }

  const appShell = document.querySelector(".app-shell");
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  if (appShell && sidebarToggle) {
    const storageKey = "spc-clearance-sidebar-hidden";
    const setSidebarState = (hidden) => {
      appShell.classList.toggle("sidebar-hidden", hidden);
      sidebarToggle.setAttribute("aria-expanded", String(!hidden));
      sidebarToggle.setAttribute(
        "title",
        hidden ? "Show sidebar" : "Hide sidebar",
      );
      sidebarToggle.setAttribute(
        "aria-label",
        hidden ? "Show sidebar" : "Hide sidebar",
      );
    };
    setSidebarState(localStorage.getItem(storageKey) === "true");
    sidebarToggle.addEventListener("click", () => {
      const hidden = !appShell.classList.contains("sidebar-hidden");
      setSidebarState(hidden);
      localStorage.setItem(storageKey, String(hidden));
    });
  }

  document
    .querySelectorAll("[data-print]")
    .forEach((button) =>
      button.addEventListener("click", () => window.print()),
    );
  document.querySelectorAll("[data-preview-form]").forEach((form) => {
    const input = form.querySelector('input[type="file"]');
    const preview = form.querySelector("[data-file-preview]");
    const content = form.querySelector("[data-preview-content]");
    const submit = form.querySelector(".upload-submit");
    const clear = form.querySelector("[data-preview-clear]");

    const clearPreview = () => {
      input.value = "";
      content.replaceChildren();
      preview.hidden = true;
      submit.disabled = true;
      submit.hidden = true;
    };

    input.addEventListener("change", () => {
      const file = input.files[0];
      if (!file) {
        clearPreview();
        return;
      }
      content.replaceChildren();
      preview.hidden = false;
      submit.disabled = false;
      submit.hidden = false;
      const fileUrl = URL.createObjectURL(file);
      if (file.type.startsWith("image/")) {
        const image = document.createElement("img");
        image.src = fileUrl;
        image.alt = `Preview of ${file.name}`;
        image.className = "preview-image";
        content.append(image);
      } else if (file.type === "application/pdf") {
        const frame = document.createElement("iframe");
        frame.src = fileUrl;
        frame.title = `Preview of ${file.name}`;
        frame.className = "preview-pdf";
        content.append(frame);
      } else {
        const card = document.createElement("div");
        card.className = "preview-document";
        card.textContent = `Ready to send: ${file.name}`;
        content.append(card);
      }
    });

    clear.addEventListener("click", clearPreview);
  });
});
