(() => {
  const script = document.currentScript;
  const widgetId = script?.dataset.widgetId;
  if (!widgetId) return;

  const apiBase = new URL(script.src).origin;
  const configUrl = `${apiBase}/api/public/widgets/${widgetId}/config`;
  const submissionUrl = `${apiBase}/api/public/widgets/${widgetId}/submissions`;

  const text = (tag, value) => {
    const element = document.createElement(tag);
    element.textContent = value || "";
    return element;
  };

  fetch(configUrl)
    .then((response) => response.ok ? response.json() : Promise.reject(response))
    .then((config) => {
      const form = document.createElement("form");
      form.append(text("h2", config.title));
      if (config.description) form.append(text("p", config.description));

      config.fields.forEach((field) => {
        const label = text("label", field.label || field.name);
        const input = document.createElement("input");
        input.name = field.name;
        input.type = field.type || "text";
        input.required = Boolean(field.required);
        label.append(input);
        form.append(label);
      });

      const honeypot = document.createElement("input");
      honeypot.name = "website";
      honeypot.tabIndex = -1;
      honeypot.autocomplete = "off";
      honeypot.style.display = "none";
      form.append(honeypot);

      const button = text("button", config.button_text);
      button.type = "submit";
      form.append(button);

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const fields = Object.fromEntries(new FormData(form));
        const spamValue = fields.website || "";
        delete fields.website;
        fetch(submissionUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ fields, honeypot: spamValue }),
        }).then((response) => {
          if (!response.ok) return Promise.reject(response);
          form.replaceChildren(text("p", "Thanks - we received your submission."));
        }).catch(() => form.append(text("p", "We could not submit this form. Please try again.")));
      });
      script.insertAdjacentElement("afterend", form);
    })
    .catch(() => {});
})();
