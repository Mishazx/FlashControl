"use strict";

const form = document.getElementById("login-form");
const errorBox = document.getElementById("login-error");

form.addEventListener("submit", async event => {
  event.preventDefault();
  errorBox.hidden = true;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const messages = {
        403: "Нет доступа: учётка не в нужной группе Active Directory.",
        429: "Слишком много попыток. Повторите позднее.",
        503: "Каталог Active Directory недоступен.",
      };
      throw new Error(messages[response.status] || payload.detail || "Неверное имя пользователя или пароль");
    }
    window.location.replace("/");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
});
